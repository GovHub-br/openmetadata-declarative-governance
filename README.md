# OpenMetadata Declarativo

Este projeto aplica uma configuração declarativa de governança no OpenMetadata, permitindo recriar e manter domínios, personas, times, usuários e produtos de dados sem depender de operações manuais na UI.

Reconciler simples para aplicar recursos de governanca no OpenMetadata a partir
de YAML. A ideia e manter usuarios, personas, times, dominios e produtos de dados
como configuracao versionavel, com comportamento de create/update.

## O que ele gerencia

- `domains`: dominios do OpenMetadata.
- `personas`: perfis/personas do OpenMetadata.
- `times` / `teams`: times e seus dominios.
- `users`: usuarios, times, personas e senha inicial/reset.
- `data_products`: produtos de dados associados a dominios.

O fluxo respeita dependencias entre recursos:

1. cria/atualiza dominios sem owners/experts;
2. cria/atualiza personas sem owners;
3. cria/atualiza times sem owners;
4. cria/atualiza usuarios;
5. atualiza dominios com owners e experts;
6. atualiza personas com owners;
7. atualiza times com owners;
8. cria/atualiza produtos de dados.

Entidades existentes sao atualizadas com `PATCH`/JSON Patch. Entidades novas
sao criadas pelos endpoints de criacao/create-or-update da API.

## Estrutura

```text
openmetadata_script/
  Dockerfile
  requirements.txt
  run.sh
  om_apply.py
  om_apply/
    audit.py
    cli.py
    client.py
    config.py
    errors.py
    reconciler.py
    utils.py
    validation.py
  resources/
    domains.yml
    personas.yml
    teams.yml
    users.yml
    data_products.yml
```

## Configuracao

Crie ou edite `.env`:

```bash
OM_HOST=https://openmetadata.clusterlab.lappis.rocks
OM_TOKEN=seu-token
USER_MATEUS_PASSWORD=Senha@123
```

O `.env` real fica ignorado pelo Git. Use variaveis de ambiente para valores
sensiveis dentro dos YAMLs:

```yaml
password: "${USER_MATEUS_PASSWORD:-Senha@123}"
```

## Uso recomendado

A forma recomendada e dar permissao de execucao ao script uma vez e rodar por
ele. O script faz build da imagem e monta a pasta `resources/` local como volume.
Assim, se voce editar YAML, nao precisa lembrar de rebuildar a imagem manualmente:

```bash
chmod +x run.sh
./run.sh
```

Dry-run:

```bash
./run.sh --dry-run
```

Validar somente o template, sem chamar a API:

```bash
./run.sh --validate-only
```

## Docker manual

Build:

```bash
docker build -t openmetadata-apply openmetadata_script
```

Aplicar a pasta modular local:

```bash
docker run --rm \
  --env-file .env \
  -v "$PWD/resources:/data/resources:ro" \
  openmetadata-apply \
  --file /data/resources
```

Aplicar um arquivo unico, caso voce prefira esse formato:

```bash
docker run --rm \
  --env-file .env \
  -v "$PWD/resources.yml:/data/resources.yml:ro" \
  openmetadata-apply \
  --file /data/resources.yml
```

Evite rodar sem montar os resources:

```bash
docker run --rm --env-file .env openmetadata-apply
```

Esse comando nao monta os YAMLs locais e deve falhar com uma mensagem orientando
a usar volume ou `run.sh`. Isso evita aplicar um arquivo antigo copiado para a
imagem em algum build anterior.

## Auditoria de erros

Erros retornados pela API sao registrados em JSON Lines. Por padrao, dentro do
container, o caminho e:

```text
/tmp/om_apply_audit.jsonl
```

Para persistir o log localmente:

```bash
mkdir -p logs

docker run --rm \
  --env-file .env \
  -e OM_AUDIT_LOG=/logs/audit.jsonl \
  -v "$PWD/logs:/logs" \
  -v "$PWD/resources:/data/resources:ro" \
  openmetadata-apply \
  --file /data/resources
```

Campos sensiveis como senha e token sao mascarados no log.

## Regras e validacoes

O `--validate-only` checa regras que ja conhecemos da instancia dev:

- senha deve ter 8 a 56 caracteres;
- senha precisa ter maiuscula, minuscula, digito e caractere especial;
- entidades com mais de um owner nao podem misturar ou repetir owner `team`;
- para multiplos owners, use owners do tipo `user`;
- `users` aceita apenas um dominio; se houver mais de um, o script usa o
  primeiro e emite aviso;
- `personas` podem declarar `dominios` e `proprietarios`;
- referencias podem ser feitas por `name`, FQN ou `displayName`.

## Referencias

Referencias aceitam formato tipado:

```yaml
proprietarios:
  - team:mgi-data-engineering
especialistas:
  - user:arthuralves1538
personas:
  - data-security-specialist
```

Quando o tipo e omitido, o script assume:

- owner de dominio/produto: `team`;
- expert: `user`;
- owner de time: `user`;
- owner de persona: `user`;
- itens de `times` em usuario: `team`;
- itens de `personas` em usuario: `persona`.

## Campos mais usados

As chaves podem ser em portugues ou no formato da API:

- `nome` / `name`
- `nome_exibicao` / `displayName`
- `descricao` / `description`
- `tipo_dominio` / `domainType`
- `proprietarios` / `owners`
- `especialistas` / `experts`
- `dominio` / `domain`
- `dominios` / `domains`
- `times` / `teams`
- `senha` / `password`
- `confirmar_senha` / `confirmPassword`
- `padrao` / `default`

## Desenvolvimento

Validar sintaxe Python:

```bash
python3 -m py_compile \
  om_apply.py \
  om_apply/*.py
```

Rodar localmente sem Docker:

```bash
export OM_HOST="https://openmetadata.clusterlab.lappis.rocks"
export OM_TOKEN="seu-token"

python3 om_apply.py \
  --file resources \
  --dry-run
```
