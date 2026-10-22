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
- `policies`: regras de acesso (efeito, recursos, operacoes, condicao).
- `roles`: conjuntos de policies, dados a time (`papeis_padrao`) ou usuario
  (`papeis`).

Policies e roles sao declaradas a mao: o `--export` nao as gera, porque a
instancia tem as embutidas e as de outros repositorios, que nao sao deste.

O fluxo respeita dependencias entre recursos:

1. cria/atualiza policies, depois roles;
1. cria/atualiza dominios sem owners/experts;
2. cria/atualiza personas sem owners;
3. cria/atualiza times sem owners;
4. cria/atualiza usuarios;
5. atualiza dominios com owners e experts;
6. atualiza personas com owners;
7. atualiza times com owners;
8. cria/atualiza produtos de dados.

Entidades existentes sao atualizadas com `PATCH`/JSON Patch contendo **so os
campos que diferem** da instancia; sem diferenca, nenhuma chamada e feita.
Rodar o apply duas vezes seguidas termina com `0 atualizados`. Entidades novas
sao criadas pelos endpoints de criacao/create-or-update da API.

O apply nao remove nada: o que existe na instancia e nao esta no YAML fica
como esta.

## Perfil de consumo por dominio

O time `mcid-consumidores` da a quem entra nele a role `MCidLeitorDominioRole`:
ve so os ativos do dominio MCid (subdominios inclusive) e sugere mudanca por
Task, sem editar direto.

Ao por alguem no time, declare tambem no usuario os dominios do time
(`MCid` e `MCid.Habitacao`). A pagina do ativo respeita a heranca do time, mas
a busca do OpenMetadata so considera os dominios diretos e exatos do usuario;
sem eles a pessoa abre a tabela, mas nao a encontra. A validacao recusa membro
que nao declara os dominios do time.

Limites conferidos na instancia 1.13.3 (detalhes em `resources/policies.yml`):
ativo sem dominio continua visivel (comportamento intencional do
OpenMetadata), e ate a 1.13.3 o GET da API que nao pede `domains` devolve o
ativo bloqueado. Este segundo esta corrigido na 1.13.4+.

## Dominios externos

A instancia e compartilhada entre ministerios, e alguns mantem a propria
hierarquia de dominios e produtos pelo sync de governanca do repositorio deles
(o MCid em `data-application-cidades`, por exemplo). Essas hierarquias ficam
listadas em `dominios_externos`, no `domains.yml`:

```yaml
dominios_externos:
  - Cultura
  - MCid
```

Elas podem ser **referenciadas** (dominio de usuario, de time, de persona), mas
declarar um dominio ou produto dentro delas e erro de validacao. Assim cada
entidade tem um unico escritor.

## Estrutura

```text
openmetadata_script/
  Dockerfile
  requirements.txt
  requirements-dev.txt
  run.sh
  om_apply.py
  om_apply/
    audit.py
    cli.py
    client.py
    config.py
    diff.py
    errors.py
    export.py
    reconciler.py
    utils.py
    validation.py
  tests/
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
```

O `.env` real fica ignorado pelo Git. Use variaveis de ambiente para valores
sensiveis dentro dos YAMLs.

### E-mail e senha de usuario

Este repositorio e publico, entao **nenhum e-mail pessoal e versionado**.
Usuario existente e identificado pelo `nome`; o e-mail so e exigido para criar
um usuario novo, e vem de variavel:

```yaml
users:
  - nome: fulano
    email: "${USER_FULANO_EMAIL}"
    senha: "${USER_FULANO_PASSWORD}"
```

No CI essas variaveis vem do secret `OM_RESOURCE_ENV` (uma linha
`CHAVE=valor` por variavel). A saida do dry-run e o log de auditoria mascaram
`email`, `password` e `token`.

## Exportar o estado da instancia

Para alinhar o repositorio com a instancia (por exemplo, depois de alguem
mexer pela interface):

```bash
python3 om_apply.py --export resources
```

Os YAMLs sao reescritos a partir da instancia, preservando os
`dominios_externos` ja declarados. Ficam de fora as hierarquias externas, o
time `Organization`, bots, o usuario `admin` embutido e qualquer e-mail. Logo
depois de um export, `--dry-run` deve terminar com `0 criados, 0 atualizados`.

## Uso recomendado

A forma recomendada e dar permissao de execucao ao script uma vez e rodar por
ele. O script faz build da imagem e monta a pasta `resources/` local como volume.
Assim, se voce editar YAML, nao precisa lembrar de rebuildar a imagem manualmente:

```bash
chmod +x run.sh
./run.sh
```

Dry-run (consulta a instancia e mostra so o que mudaria, sem escrever):

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
- nenhum dominio ou produto pode ser declarado dentro de `dominios_externos`;
- `personas` podem declarar `dominios`; persona nao tem `proprietarios` no
  OpenMetadata (a API recusa o campo);
- referencias podem ser feitas por `name`, FQN ou `displayName`. Referencia
  que nao existe na instancia falha tambem no dry-run.

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
- `papeis` / `roles`
- `papeis_padrao` / `defaultRoles` (time: role herdada por todos os membros)
- `politicas` / `policies` (role)
- `regras` / `rules`, e em cada regra `efeito`, `recursos`, `operacoes`,
  `condicao`
- `administrador` / `isAdmin` (so `true` e exportado; para revogar, declare
  `false`)

## CI

- **Todo PR**: testes, `--validate-only` e, em PR do proprio repositorio, um
  dry-run contra a instancia. O resultado vira um comentario no PR (atualizado
  a cada push), com o que o merge vai criar ou alterar.
- **Push na main** que mexa em `resources/` ou no codigo: apply, um por vez
  (`concurrency`), no environment `openmetadata`.

Configuracao no GitHub:

| onde | nome | conteudo |
|---|---|---|
| variable | `OM_HOST` | URL da instancia |
| secret | `OM_TOKEN` | token do bot de governanca (precisa de permissao de admin para criar time, usuario, role e policy) |
| secret | `OM_RESOURCE_ENV` | variaveis usadas nos YAMLs, uma `CHAVE=valor` por linha |
| environment | `openmetadata` | onde o apply roda; pode exigir aprovacao |

### Bot do CI

O CI aplica com o bot `govhub-governanca-bot`, e nao com um usuario pessoal.
Ele tem uma unica role, `GovernancaComoCodigoRole`, cuja policy
`GovernancaComoCodigoPolicy` libera todas as operacoes **so** nos recursos que
este reconciler gerencia (team, user, persona, domain, dataProduct, role,
policy, eventsubscription). Nao alcanca ativo de dados.

Nao confundir com o `governance-bot`, que e embutido do OpenMetadata e roda os
Governance Workflows.

Ao criar um bot, o OpenMetadata acrescenta a `DefaultBotRole`, que **nega
`EditDisplayName` em tudo** (negacao vence permissao). Ela foi retirada deste
bot; sem isso, mudar um `nome_exibicao` no YAML quebraria o apply. Se o bot
for recriado, retire-a de novo.

Para trocar o token: no OpenMetadata, Settings > Bots >
`govhub-governanca-bot` > revogar e gerar novo; depois
`gh secret set OM_TOKEN` neste repositorio.

## Desenvolvimento

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pytest -q
```

Os testes usam um OpenMetadata em memoria (`tests/fake_om.py`), sem rede.

Rodar localmente sem Docker:

```bash
export OM_HOST="https://openmetadata.clusterlab.lappis.rocks"
export OM_TOKEN="seu-token"

python3 om_apply.py \
  --file resources \
  --dry-run
```
