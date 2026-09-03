# NATS Gateway para Mnemosyne

Camada de comunicação em Zig 0.16+ que fornece acesso ao banco de dados SQLite do Mnemosyne exclusivamente via NATS.

## Estrutura do Projeto

```
nats_gateway/
├── src/
│   └── main.zig          # Código principal do gateway
├── build.zig             # Build script do Zig
└── README.md             # Esta documentação
```

## Funcionalidades

O gateway expõe as seguintes operações via NATS:

### Memory Operations
- `mnemosyne.memory.add` - Adiciona nova memória
- `mnemosyne.memory.get` - Recupera memória por ID
- `mnemosyne.memory.delete` - Remove memória por ID
- `mnemosyne.memory.search` - Busca memórias por conteúdo
- `mnemosyne.memory.list` - Lista todas as memórias (últimas 50)

### BEAM Operations
- `mnemosyne.beam.add` - Adiciona memória working memory
- `mnemosyne.beam.get` - Recupera memória BEAM
- `mnemosyne.beam.clear` - Limpa working memory

## Protocolo de Comunicação

### Formato das Mensagens

Todas as mensagens utilizam JSON como payload:

**Exemplo - Adicionar Memória:**
```json
{
  "content": "Conteúdo da memória"
}
```

**Exemplo - Buscar Memória:**
```json
{
  "id": 123
}
```

**Exemplo - Buscar Memória:**
```json
{
  "query": "termo de busca"
}
```

### Respostas

**Sucesso:**
```json
{
  "success": true,
  "data": "{\"id\": 1, \"success\": true}"
}
```

**Erro:**
```json
{
  "success": false,
  "error_msg": "Memory not found"
}
```

## Compilação

### Pré-requisitos
- Zig 0.16 ou superior
- Servidor NATS rodando

### Build

```bash
cd nats_gateway

# Build em modo release
zig build-exe src/main.zig -O ReleaseFast

# Build em modo debug
zig build-exe src/main.zig -O Debug

# Ou usando o sistema de build do Zig
zig build
```

## Uso

### Iniciar o Gateway

```bash
# Com configurações padrão (localhost:4222, ./mnemosyne.db)
./nats_gateway

# Com opções personalizadas
./nats_gateway --nats-host=localhost --nats-port=4222 --db-path=/path/to/mnemosyne.db
```

### Opções de Linha de Comando

```
--nats-host=<host>       Host do servidor NATS (padrão: localhost)
--nats-port=<porta>      Porta do servidor NATS (padrão: 4222)
--db-path=<caminho>      Caminho do banco SQLite (padrão: ./mnemosyne.db)
--subject-prefix=<prefixo> Prefixo dos tópicos NATS (padrão: mnemosyne)
--help                   Mostrar ajuda
```

## Exemplo de Cliente

### Python

```python
import nats
import json
import asyncio

async def main():
    nc = await nats.connect("nats://localhost:4222")
    
    # Adicionar memória
    await nc.request(
        "mnemosyne.memory.add",
        json.dumps({"content": "Minha nova memória"}).encode()
    )
    
    # Buscar memória
    response = await nc.request(
        "mnemosyne.memory.get",
        json.dumps({"id": 1}).encode()
    )
    print(json.loads(response.data))
    
    # Buscar memórias
    response = await nc.request(
        "mnemosyne.memory.search",
        json.dumps({"query": "minha"}).encode()
    )
    print(json.loads(response.data))
    
    await nc.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Node.js

```javascript
const { connect } = require('@nats-io/transport-node');

async function main() {
    const nc = await connect({ servers: 'nats://localhost:4222' });
    
    // Adicionar memória
    const addResponse = await nc.request(
        'mnemosyne.memory.add',
        JSON.stringify({ content: 'Minha memória' })
    );
    console.log(JSON.parse(addResponse.string()));
    
    // Listar memórias
    const listResponse = await nc.request('mnemosyne.memory.list');
    console.log(JSON.parse(listResponse.string()));
    
    await nc.drain();
}

main().catch(console.error);
```

## Arquitetura

O gateway implementa:

1. **Cliente NATS nativo** - Implementação direta do protocolo NATS sem dependências externas
2. **SQLite embutido** - Usa a biblioteca padrão do Zig para SQLite
3. **Request-Reply** - Suporte a padrões síncronos e assíncronos
4. **Tratamento de erros** - Respostas padronizadas com códigos de erro

## Tópicos NATS

Todos os tópicos seguem o padrão: `mnemosyne.<tipo>.<operacao>`

| Tópico | Descrição | Payload |
|--------|-----------|---------|
| `mnemosyne.memory.add` | Adiciona memória | `{"content": "..."}` |
| `mnemosyne.memory.get` | Obtém memória | `{"id": 123}` |
| `mnemosyne.memory.delete` | Remove memória | `{"id": 123}` |
| `mnemosyne.memory.search` | Busca memórias | `{"query": "..."}` |
| `mnemosyne.memory.list` | Lista memórias | `{}` |
| `mnemosyne.beam.add` | Adiciona BEAM | `{"content": "..."}` |
| `mnemosyne.beam.get` | Obtém BEAM | `{"id": 123}` |
| `mnemosyne.beam.clear` | Limpa BEAM | `{}` |

## Integração com Mnemosyne

O gateway se conecta diretamente ao banco de dados SQLite usado pelo Mnemosyne, localizado em:
- Padrão: `~/.hermes/mnemosyne/data/mnemosyne.db`
- Bancos nomeados: `~/.hermes/mnemosyne/data/banks/<nome>/mnemosyne.db`

Use a opção `--db-path` para especificar o caminho correto do banco de dados.

## Considerações de Performance

- Conexões persistentes ao NATS e SQLite
- Processamento assíncrono de mensagens
- Alocação de memória otimizada
- Suitable para ambientes de produção

## License

MIT
