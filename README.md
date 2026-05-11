# OpenMetadata Declarativo

Este projeto aplica uma configuração declarativa de governança no OpenMetadata, permitindo recriar e manter domínios, times, usuários e produtos de dados sem depender de operações manuais na UI.

Reconciler simples para aplicar recursos de governanca no OpenMetadata a partir
de YAML. A ideia e manter usuarios, times, dominios e produtos de dados como
configuracao versionavel, com comportamento de create/update.

## O que ele gerencia

- `domains`: dominios do OpenMetadata.
- `times` / `teams`: times e seus dominios.
- `users`: usuarios, times, personas e senha inicial/reset.
- `data_products`: produtos de dados associados a dominios.

O fluxo respeita dependencias entre recursos:

1. cria/atualiza dominios sem referencias;
2. cria/atualiza times sem owners;
3. cria/atualiza usuarios;
4. atualiza dominios com owners e experts;
5. atualiza times com owners;
6. cria/atualiza produtos de dados.

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
    teams.yml
    users.yml
    data_products.yml
```

## Configuracao

Crie ou edite `openmetadata_script/.env`:

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

O atalho abaixo faz build da imagem e monta a pasta `resources/` local como
volume. Assim, se voce editar YAML, nao precisa lembrar de rebuildar a imagem
manualmente:

```bash
sh openmetadata_script/run.sh
```

Dry-run:

```bash
sh openmetadata_script/run.sh --dry-run
```

Validar somente o template, sem chamar a API:

```bash
sh openmetadata_script/run.sh --validate-only
```

## Docker manual

Build:

```bash
docker build -t openmetadata-apply openmetadata_script
```

Aplicar a pasta modular local:

```bash
docker run --rm \
  --env-file openmetadata_script/.env \
  -v "$PWD/openmetadata_script/resources:/data/resources:ro" \
  openmetadata-apply \
  --file /data/resources
```

Aplicar um arquivo unico, caso voce prefira esse formato:

```bash
docker run --rm \
  --env-file openmetadata_script/.env \
  -v "$PWD/openmetadata_script/resources.yml:/data/resources.yml:ro" \
  openmetadata-apply \
  --file /data/resources.yml
```

Usar o YAML empacotado na imagem:

```bash
docker run --rm --env-file openmetadata_script/.env openmetadata-apply
```

Esse ultimo comando so enxerga alteracoes em YAML depois de um novo
`docker build`, porque os arquivos ficam copiados dentro da imagem.

## Auditoria de erros

Erros retornados pela API sao registrados em JSON Lines. Por padrao, dentro do
container, o caminho e:

```text
/tmp/om_apply_audit.jsonl
```

Para persistir o log localmente:

```bash
mkdir -p openmetadata_script/logs

docker run --rm \
  --env-file openmetadata_script/.env \
  -e OM_AUDIT_LOG=/logs/audit.jsonl \
  -v "$PWD/openmetadata_script/logs:/logs" \
  -v "$PWD/openmetadata_script/resources:/data/resources:ro" \
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
- itens de `times` em usuario: `team`.

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

## Desenvolvimento

Validar sintaxe Python:

```bash
python3 -m py_compile \
  openmetadata_script/om_apply.py \
  openmetadata_script/om_apply/*.py
```

Rodar localmente sem Docker:

```bash
export OM_HOST="https://openmetadata.clusterlab.lappis.rocks"
export OM_TOKEN="seu-token"

python3 openmetadata_script/om_apply.py \
  --file openmetadata_script/resources \
  --dry-run
```
