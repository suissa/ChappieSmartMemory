const std = @import("std");
const net = std.net;
const posix = std.posix;

const log = std.log.scoped(.nats_gateway);

// Configurações do serviço
const Config = struct {
    nats_host: []const u8 = "localhost",
    nats_port: u16 = 4222,
    db_path: []const u8 = "./mnemosyne.db",
    subject_prefix: []const u8 = "mnemosyne",
};

// Cliente NATS simplificado
const NatsClient = struct {
    stream: net.Stream,
    allocator: std.mem.Allocator,
    server_id: []u8,
    version: []u8,

    pub fn connect(allocator: std.mem.Allocator, host: []const u8, port: u16) !NatsClient {
        log.info("Conectando ao NATS em {s}:{d}...", .{ host, port });

        const address = try net.Address.resolveIp(host, port);
        const stream = try net.tcpConnectToAddress(address);

        var client = NatsClient{
            .stream = stream,
            .allocator = allocator,
            .server_id = "",
            .version = "",
        };

        // Ler mensagem INFO do servidor
        try client.readInfoMessage();

        // Enviar CONNECT
        try client.sendConnect();

        // Enviar PING inicial
        try client.sendPing();

        // Ler PONG
        try client.readPong();

        log.info("Conectado ao servidor NATS", .{});
        return client;

    fn readInfoMessage(self: *NatsClient) !void {
        var reader = self.stream.reader();
        var line_buf: [1024]u8 = undefined;

        // Ler linha INFO
        const line = try reader.readUntilDelimiter(&line_buf, '\n');
        
        if (std.mem.startsWith(u8, line, "INFO ")) {
            const json_str = line["INFO ".len..];
            const iter = std.json.parseFromSliceLeaky(std.json.Value, self.allocator, json_str, .{}) catch {
                log.warn("Falha ao parsear INFO JSON", .{});
                return;
            };
            
            if (iter.object) |obj| {
                if (obj.get("server_id")) |val| {
                    if (val.string) |s| self.server_id = s;
                if (obj.get("version")) |val| {
                    if (val.string) |s| self.version = s;
            
            log.info("Servidor NATS: ID={s}, Versão={s}", .{ self.server_id, self.version });

    fn sendConnect(self: *NatsClient) !void {
        const connect_msg = 
            \\CONNECT {"verbose":false,"pedantic":false,"tls_required":false,"name":"zig-nats-gateway"}
        ;
        try self.stream.writeAll(connect_msg ++ "\r\n");

    fn sendPing(self: *NatsClient) !void {
        try self.stream.writeAll("PING\r\n");

    fn readPong(self: *NatsClient) !void {
        var reader = self.stream.reader();
        var buf: [8]u8 = undefined;
        _ = try reader.read(&buf);
        // Espera-se "PONG\r\n"

    pub fn subscribe(self: *NatsClient, subject: []const u8, sid: []const u8) !void {
        const sub_msg = try std.fmt.allocPrint(
            self.allocator,
            "SUB {s} {s}\r\n",
            .{ subject, sid }
        );
        defer self.allocator.free(sub_msg);
        try self.stream.writeAll(sub_msg);

    pub fn publish(self: *NatsClient, subject: []const u8, data: []const u8) !void {
        const pub_msg = try std.fmt.allocPrint(
            self.allocator,
            "PUB {s} {d}\r\n{s}\r\n",
            .{ subject, data.len, data }
        );
        defer self.allocator.free(pub_msg);
        try self.stream.writeAll(pub_msg);

    pub fn publishReply(self: *NatsClient, subject: []const u8, reply_to: []const u8, data: []const u8) !void {
        const pub_msg = try std.fmt.allocPrint(
            self.allocator,
            "PUB {s} {s} {d}\r\n{s}\r\n",
            .{ subject, reply_to, data.len, data }
        );
        defer self.allocator.free(pub_msg);
        try self.stream.writeAll(pub_msg);

    pub fn readMessage(self: *NatsClient, allocator: std.mem.Allocator) !?NatsMessage {
        var reader = self.stream.reader();
        var line_buf: [4096]u8 = undefined;

        while (true) {
            const line = reader.readUntilDelimiter(&line_buf, '\n') catch {
                
                    if (true) return null; // EndOfStream
            };

            // Remover \r se existir
            const clean_line = std.mem.trimRight(u8, line, "\r");

            if (std.mem.startsWith(u8, clean_line, "MSG ")) {
                return try self.parseMessage(clean_line, allocator);
            } else if (std.mem.eql(u8, clean_line, "PING")) {
                try self.stream.writeAll("PONG\r\n");
            } else if (std.mem.eql(u8, clean_line, "PONG")) {
                // Ignorar PONG
            } else if (std.mem.startsWith(u8, clean_line, "+OK")) {
                // OK do servidor
            } else if (std.mem.startsWith(u8, clean_line, "-ERR")) {
                log.err("Erro do servidor NATS: {s}", .{clean_line});

    fn parseMessage(self: *NatsClient, header_line: []const u8, allocator: std.mem.Allocator) !NatsMessage {
        var parts = std.mem.splitScalar(u8, header_line, ' ');
        _ = parts.next(); // "MSG"
        
        const subject = parts.next() orelse return error.InvalidMessage;
        const sid = parts.next() orelse return error.InvalidMessage;
        
        // Verificar se tem reply_to
        var maybe_reply_to: ?[]const u8 = null;
        var data_len_str: []const u8 = undefined;
        
        const next = parts.next() orelse return error.InvalidMessage;
        if (std.ascii.isDigit(next[0])) {
            data_len_str = next;
        } else {
            maybe_reply_to = next;
            data_len_str = parts.next() orelse return error.InvalidMessage;
        
        const data_len = std.fmt.parseInt(usize, data_len_str, 10) catch return error.InvalidDataLength;
        
        // Ler dados da mensagem
        const data_buf = try allocator.alloc(u8, data_len);
        errdefer allocator.free(data_buf);
        
        const bytes_read = try self.stream.read(data_buf);
        if (bytes_read != data_len) return error.IncompleteMessage;
        
        // Ler \r\n após os dados
        var crlf: [2]u8 = undefined;
        _ = try self.stream.read(&crlf);
        
        return NatsMessage{
            .subject = subject,
            .sid = sid,
            .reply_to = maybe_reply_to,
            .data = data_buf,
        };

    pub fn destroy(self: *NatsClient) void {
        self.stream.close();
};

// Mensagem NATS recebida
const NatsMessage = struct {
    subject: []const u8,
    sid: []const u8,
    reply_to: ?[]const u8,
    data: []u8,
};

// Resposta padronizada
const Response = struct {
    success: bool,
    data: ?[]const u8 = null,
    error_msg: ?[]const u8 = null,
};

// Gateway principal
const NatsGateway = struct {
    nats: NatsClient,
    db: std.sqlite.Db,
    config: Config,
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator, config: Config) !NatsGateway {
        log.info("Inicializando NATS Gateway...", .{});

        // Conectar ao NATS
        const nats = try NatsClient.connect(allocator, config.nats_host, config.nats_port);

        // Abrir banco SQLite
        const db = try std.sqlite.open(config.db_path);

        log.info("Banco de dados aberto: {s}", .{config.db_path});

        return .{
            .nats = nats,
            .db = db,
            .config = config,
            .allocator = allocator,
        };

    pub fn deinit(self: *NatsGateway) void {
        self.db.close();
        self.nats.destroy();

    pub fn start(self: *NatsGateway) !void {
        log.info("Iniciando subscrições NATS...", .{});

        // Subscrever aos tópicos de operação
        const subscriptions = [_]struct {
            topic: []const u8,
            sid: []const u8,
        }{
            .{ .topic = "mnemosyne.memory.add", .sid = "1" },
            .{ .topic = "mnemosyne.memory.get", .sid = "2" },
            .{ .topic = "mnemosyne.memory.delete", .sid = "3" },
            .{ .topic = "mnemosyne.memory.search", .sid = "4" },
            .{ .topic = "mnemosyne.memory.list", .sid = "5" },
            .{ .topic = "mnemosyne.beam.add", .sid = "6" },
            .{ .topic = "mnemosyne.beam.get", .sid = "7" },
            .{ .topic = "mnemosyne.beam.clear", .sid = "8" },
        };

        for (subscriptions) |sub| {
            try self.nats.subscribe(sub.topic, sub.sid);
            log.info("Subscrito ao tópico: {s}", .{sub.topic});

        log.info("Gateway pronto para receber mensagens", .{});

        // Loop principal de processamento
        while (true) {
            const msg = try self.nats.readMessage(self.allocator) orelse {
                log.warn("Conexão NATS fechada", .{});
                break;
            };
            defer self.allocator.free(msg.data);

            self.handleMessage(msg) catch {
                log.err("Erro ao processar mensagem", .{});
                if (msg.reply_to) |reply_to| {
                    self.sendReply(reply_to, .{
                        .success = false,
                        .error_msg = "Internal server error",
                    }) catch {};
            };

    fn handleMessage(self: *NatsGateway, msg: NatsMessage) !void {
        log.debug("Mensagem recebida: {s}", .{msg.subject});

        const response = self.processMessage(msg.subject, msg.data) catch {
            log.err("Erro ao processar mensagem", .{});
            return error.ProcessFailed;
        };

        if (msg.reply_to) |reply_to| {
            try self.sendReply(reply_to, response);

    fn processMessage(self: *NatsGateway, subject: []const u8, data: []const u8) !Response {
        // Extrair operação do subject
        var parts = std.mem.splitScalar(u8, subject, '.');
        _ = parts.next(); // prefixo
        _ = parts.next(); // mnemosyne
        const operation = parts.next() orelse return Response{
            .success = false,
            .error_msg = "Invalid subject format",
        };

        // Processar operação
        if (std.mem.eql(u8, operation, "add")) {
            return self.handleAdd(data);
        } else if (std.mem.eql(u8, operation, "get")) {
            return self.handleGet(data);
        } else if (std.mem.eql(u8, operation, "delete")) {
            return self.handleDelete(data);
        } else if (std.mem.eql(u8, operation, "search")) {
            return self.handleSearch(data);
        } else if (std.mem.eql(u8, operation, "list")) {
            return self.handleList(data);
        } else {
            return Response{
                .success = false,
                .error_msg = "Unknown operation",
            };

    fn handleAdd(self: *NatsGateway, data: []const u8) !Response {
        // Parse JSON da mensagem
        var parsed = std.json.parseFromSlice(std.json.Value, self.allocator, data, .{}) catch {
            return Response{
                .success = false,
                .error_msg = "Invalid JSON payload",
            };
        };
        defer parsed.deinit();

        const obj = parsed.value.object orelse return Response{
            .success = false,
            .error_msg = "Payload must be a JSON object",
        };

        const content = obj.get("content") orelse return Response{
            .success = false,
            .error_msg = "Missing 'content' field",
        };

        const content_str = content.string orelse return Response{
            .success = false,
            .error_msg = "'content' must be a string",
        };

        // Inserir no banco de dados
        const stmt = self.db.prepare(
            \\INSERT INTO working_memory (content, timestamp, created_at)
            \\VALUES (?, ?, ?)
        ) catch {
            return Response{
                .success = false,
                .error_msg = "Database error",
            };
        };
        defer stmt.deinit();

        const now = std.time.timestamp();
        stmt.bindText(1, content_str) catch {};
        stmt.bindInt(2, now) catch {};
        stmt.bindInt(3, now) catch {};

        stmt.step() catch {
            return Response{
                .success = false,
                .error_msg = "Failed to insert",
            };
        };

        const row_id = self.db.lastInsertRowId();

        // Preparar resposta
        const response_data = try std.fmt.allocPrint(
            self.allocator,
            "{{\"id\": {d}, \"success\": true}}",
            .{row_id}
        );

        return Response{
            .success = true,
            .data = response_data,
        };

    fn handleGet(self: *NatsGateway, data: []const u8) !Response {
        var parsed = std.json.parseFromSlice(std.json.Value, self.allocator, data, .{}) catch {
            return Response{
                .success = false,
                .error_msg = "Invalid JSON payload",
            };
        };
        defer parsed.deinit();

        const obj = parsed.value.object orelse return Response{
            .success = false,
            .error_msg = "Payload must be a JSON object",
        };

        const id_val = obj.get("id") orelse return Response{
            .success = false,
            .error_msg = "Missing 'id' field",
        };

        const id = id_val.int orelse return Response{
            .success = false,
            .error_msg = "'id' must be an integer",
        };

        // Buscar no banco de dados
        const stmt = self.db.prepare(
            \\SELECT id, content, timestamp, metadata_json
            \\FROM working_memory
            \\WHERE id = ?
        ) catch {
            return Response{
                .success = false,
                .error_msg = "Database error",
            };
        };
        defer stmt.deinit();

        stmt.bindInt(1, @intCast(id)) catch {};

        if (stmt.step() catch false) {
            const content = stmt.getText(1) orelse "";
            const timestamp = stmt.getInt(2);
            const metadata = stmt.getText(3) orelse "{}";

            const response_data = try std.fmt.allocPrint(
                self.allocator,
                \\{{"id": {d}, "content": "{s}", "timestamp": {d}, "metadata": {s}}}
            ,
                .{ id, content, timestamp, metadata }
            );

            return Response{
                .success = true,
                .data = response_data,
            };
        } else {
            return Response{
                .success = false,
                .error_msg = "Memory not found",
            };

    fn handleDelete(self: *NatsGateway, data: []const u8) !Response {
        var parsed = std.json.parseFromSlice(std.json.Value, self.allocator, data, .{}) catch {
            return Response{
                .success = false,
                .error_msg = "Invalid JSON payload",
            };
        };
        defer parsed.deinit();

        const obj = parsed.value.object orelse return Response{
            .success = false,
            .error_msg = "Payload must be a JSON object",
        };

        const id_val = obj.get("id") orelse return Response{
            .success = false,
            .error_msg = "Missing 'id' field",
        };

        const id = id_val.int orelse return Response{
            .success = false,
            .error_msg = "'id' must be an integer",
        };

        // Deletar do banco de dados
        const stmt = self.db.prepare(
            \\DELETE FROM working_memory WHERE id = ?
        ) catch {
            return Response{
                .success = false,
                .error_msg = "Database error",
            };
        };
        defer stmt.deinit();

        stmt.bindInt(1, @intCast(id)) catch {};
        stmt.step() catch {};

        return Response{
            .success = true,
            .data = "{\"deleted\": true}",
        };

    fn handleSearch(self: *NatsGateway, data: []const u8) !Response {
        var parsed = std.json.parseFromSlice(std.json.Value, self.allocator, data, .{}) catch {
            return Response{
                .success = false,
                .error_msg = "Invalid JSON payload",
            };
        };
        defer parsed.deinit();

        const obj = parsed.value.object orelse return Response{
            .success = false,
            .error_msg = "Payload must be a JSON object",
        };

        const query_val = obj.get("query") orelse return Response{
            .success = false,
            .error_msg = "Missing 'query' field",
        };

        const query = query_val.string orelse return Response{
            .success = false,
            .error_msg = "'query' must be a string",
        };

        // Buscar com LIKE
        const stmt = self.db.prepare(
            \\SELECT id, content, timestamp
            \\FROM working_memory
            \\WHERE content LIKE ?
            \\LIMIT 10
        ) catch {
            return Response{
                .success = false,
                .error_msg = "Database error",
            };
        };
        defer stmt.deinit();

        const search_pattern = try std.fmt.allocPrint(
            self.allocator,
            "%{s}%",
            .{query}
        );
        defer self.allocator.free(search_pattern);

        stmt.bindText(1, search_pattern) catch {};

        var results = std.ArrayList(u8).init(self.allocator);
        defer results.deinit();

        try results.appendSlice("[");
        var first = true;

        while (stmt.step() catch false) {
            if (!first) try results.appendSlice(",");
            first = false;

            const row_id = stmt.getInt(0);
            const content = stmt.getText(1) orelse "";
            const timestamp = stmt.getInt(2);

            try std.fmt.format(
                results.writer(),
                \\{{"id": {d}, "content": "{s}", "timestamp": {d}}}
            ,
                .{ row_id, content, timestamp }
            );

        try results.appendSlice("]");

        return Response{
            .success = true,
            .data = results.items,
        };

    fn handleList(self: *NatsGateway, data: []const u8) !Response {
        // Listar todas as memórias (com limite)
        const stmt = self.db.prepare(
            \\SELECT id, content, timestamp
            \\FROM working_memory
            \\ORDER BY timestamp DESC
            \\LIMIT 50
        ) catch {
            return Response{
                .success = false,
                .error_msg = "Database error",
            };
        };
        defer stmt.deinit();

        var results = std.ArrayList(u8).init(self.allocator);
        defer results.deinit();

        try results.appendSlice("[");
        var first = true;

        while (stmt.step() catch false) {
            if (!first) try results.appendSlice(",");
            first = false;

            const row_id = stmt.getInt(0);
            const content = stmt.getText(1) orelse "";
            const timestamp = stmt.getInt(2);

            try std.fmt.format(
                results.writer(),
                \\{{"id": {d}, "content": "{s}", "timestamp": {d}}}
            ,
                .{ row_id, content, timestamp }
            );

        try results.appendSlice("]");

        return Response{
            .success = true,
            .data = results.items,
        };

    fn sendReply(self: *NatsGateway, subject: []const u8, response: Response) !void {
        const json = try std.json.stringifyAlloc(
            self.allocator,
            response,
            .{ .whitespace = .minified },
        );
        defer self.allocator.free(json);

        try self.nats.publishReply(subject, subject, json);
};

pub fn main() !void {
    
    const allocator = std.heap.page_allocator;

    // Parser de argumentos de linha de comando
    var args = std.process.args();
    _ = args.skip(); // pular nome do executável

    var config = Config{};

    while (args.next()) |arg| {
        if (std.mem.startsWith(u8, arg, "--nats-host=")) {
            config.nats_host = arg["--nats-host=".len..];
        } else if (std.mem.startsWith(u8, arg, "--nats-port=")) {
            config.nats_port = std.fmt.parseInt(u16, arg["--nats-port=".len..], 10) catch 4222;
        } else if (std.mem.startsWith(u8, arg, "--db-path=")) {
            config.db_path = arg["--db-path=".len..];
        } else if (std.mem.startsWith(u8, arg, "--subject-prefix=")) {
            config.subject_prefix = arg["--subject-prefix=".len..];
        } else if (std.mem.eql(u8, arg, "--help")) {
            std.debug.print(
                \\Uso: nats_gateway [opções]
                \\Opções:
                \\  --nats-host=<host>     Host do servidor NATS (padrão: localhost)
                \\  --nats-port=<porta>    Porta do servidor NATS (padrão: 4222)
                \\  --db-path=<caminho>    Caminho do banco SQLite (padrão: ./mnemosyne.db)
                \\  --subject-prefix=<prefixo> Prefixo dos tópicos NATS (padrão: mnemosyne)
                \\  --help                 Mostrar esta ajuda
                \\
            , .{});
            return;

    var gateway = try NatsGateway.init(allocator, config);
    defer gateway.deinit();

    try gateway.start();
