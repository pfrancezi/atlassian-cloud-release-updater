# Guia de Fluxo e Status

Este documento explica como o Atlassian Cloud Release Updater coleta dados das fontes, combina registros, cria ou atualiza issues Jira e trata os campos de ciclo de vida.

English version: [FLOW_AND_STATUS.md](FLOW_AND_STATUS.md)

## Modelo de fontes

A versão pronta para GitHub/Marketplace usa duas fontes:

| Fonte | Rótulo interno | Obrigatória? | Como é coletada | Uso principal |
|---|---|---:|---|---|
| Fonte privada do Atlassian Admin | `Private` | Não | Cookie de sessão de `admin.atlassian.com` informado pelo próprio cliente | Metadados privados/admin, datas de release, site release status, delayability e conteúdo detalhado da mudança. |
| Atlassian Community Release Notes | `Community` | Sim | API pública da Atlassian Community | Visibilidade pública da release note, status/tipo da Community, primeira data de publicação e conteúdo público detalhado. |

O parser legado do blog semanal em Confluence foi removido. O fluxo ativo não usa mais URL pública do blog, Product Section, Week Title, Week URL ou campo Rollout Flags.

## Fluxo de execução

```text
Início
  ↓
Lê configuração local e dados de conexão com Jira
  ↓
Opcionalmente coleta a fonte privada do Admin
  ↓
Coleta a fonte pública Community Release Notes
  ↓
Normaliza os payloads das fontes em um formato comum
  ↓
Combina registros por Atlassian/Admin ID, change key quando existir, ou título normalizado
  ↓
Verifica/cria opções faltantes em campos select quando habilitado
  ↓
Lê as issues existentes no projeto Jira configurado
  ↓
Para cada registro combinado:
    Procura issue correspondente por Admin ID, change key ou título
    Se a issue não existir e criação estiver habilitada:
        Cria uma nova issue Jira
    Se a issue existir:
        Monta payload de atualização somente para campos que precisam mudar
  ↓
Reconciliação issue-first:
    Revisa issues existentes que não passaram pelo loop principal das fontes
    Enriquece a issue se ela agora aparecer em alguma fonte
  ↓
Grava o JSON de ações
Fim
```

## Lógica de correspondência

O script tenta evitar duplicidade buscando uma issue existente nesta ordem:

1. `CF_ADMIN_ID`, o ID opaco da mudança no Admin/Community.
2. `CF_CHANGEKEY`, quando existir uma chave pública/provedora.
3. Título normalizado, removendo o token do resumo.

Boa prática: configurar `CF_ADMIN_ID`. Ele é o campo de correspondência mais estável para este utilitário.

## Comportamento na criação de nova issue

Quando um registro não corresponde a uma issue existente e a criação está habilitada, o script cria uma issue com:

| Área do Jira | Comportamento |
|---|---|
| Summary | Usa `[changeKey] Título` quando existe change key, senão `[adminId] Título`, senão apenas o título. |
| Description | Gerada em Atlassian Document Format a partir do conteúdo detalhado disponível. |
| Source | Define `Private`, `Community` ou ambos, conforme a origem da mudança. |
| Products | Tags técnicas de produto, combinadas e mapeadas. |
| Change Status | Define `NEW THIS WEEK` somente quando a nova issue tem fonte Private. |
| Community Status | Define `NEW THIS WEEK` quando a nova issue tem status da Community. |
| Datas da Community | Preenchidas a partir de `firstPublishedAt` e release start da Community quando disponíveis. |
| Datas privadas | Preenchidas a partir dos metadados privados do Admin quando disponíveis. |

## Campos de status e significado

Os scripts mantêm intencionalmente o ciclo de vida privado/admin separado do ciclo de vida da Community.

### Change Status

`CF_CHANGE_STATUS` representa somente o status de ciclo de vida da fonte privada do Atlassian Admin.

| Valor | Significado neste utilitário | Fonte |
|---|---|---|
| `NEW THIS WEEK` | A mudança foi criada a partir da fonte Private ou apareceu na fonte Private pela primeira vez em uma issue existente. É um marcador de acompanhamento, não necessariamente o status real da Atlassian. | Gerado pelo script |
| `COMING_SOON` | A fonte privada Admin indica que a mudança está prevista/em breve. | Private |
| `ROLLING_OUT` | A fonte privada Admin indica que a mudança está em rollout. | Private |
| `GENERALLY_AVAILABLE` | A fonte privada Admin indica que a mudança está disponível de forma geral ou teve release concluída. | Private |
| `PLANNED` | A fonte privada Admin indica que a mudança está planejada. | Private |
| `EXPERIMENT` | A fonte privada Admin classifica a mudança como experimento. | Private |
| `DEPRECATED` | A fonte privada Admin marca a mudança como depreciada. | Private |
| `ANNOUNCEMENT` | A fonte privada Admin classifica a mudança como anúncio. | Private |

`Change Status` não é derivado do status da Community. Isso evita que o ciclo de vida público sobrescreva o ciclo privado/admin.

### Community Status

`CF_COMMUNITY_STATUS` representa o status de ciclo de vida da Atlassian Community Release Notes. Ele foi pensado como campo single-select, porque apenas um status público atual deve ser armazenado por vez.

| Valor | Significado neste utilitário | Fonte |
|---|---|---|
| `NEW THIS WEEK` | A mudança foi criada a partir da Community ou apareceu na Community pela primeira vez em uma issue existente. Este é o marcador de visibilidade pública que substituiu o antigo campo Rollout Flags. | Gerado pelo script |
| Valor retornado pela API | Status retornado pela API da Community depois que o marcador da primeira semana é limpo em uma execução posterior. | Community |

Os valores exatos da Community dependem do que a API retornar. O script normaliza valores comuns de ciclo de vida, como `COMING_SOON`, `ROLLING_OUT` e `GENERALLY_AVAILABLE`.

## Como o `NEW THIS WEEK` é atualizado

### Regras de primeira aparição

| Cenário | Resultado |
|---|---|
| Nova issue criada a partir da Private | `Change Status = NEW THIS WEEK`. |
| Nova issue criada a partir da Community | `Community Status = NEW THIS WEEK`. |
| Issue existente aparece na Private pela primeira vez | Adiciona `Private` em Source e define `Change Status = NEW THIS WEEK`. |
| Issue existente aparece na Community pela primeira vez | Adiciona `Community` em Source, define `Community Status = NEW THIS WEEK`, preenche datas da Community e atualiza a descrição. |

### Regras das execuções seguintes

Em uma execução posterior, quando a issue já tem `NEW THIS WEEK`, o script troca o marcador pelo status real da mesma fonte quando esse status existe.

| Campo | Comportamento posterior |
|---|---|
| `Change Status` | Substituído pelo status real da fonte Private quando disponível. |
| `Community Status` | Substituído pelo status real da Community quando disponível. |

Exemplo para Community:

```text
Execução 1: item aparece na Community pela primeira vez
  → Community Status = NEW THIS WEEK

Execução 2: mesmo item é coletado novamente da Community
  → Community Status = ROLLING_OUT, COMING_SOON, GENERALLY_AVAILABLE ou outro status retornado pela API
```

## Comportamento das datas

Os dois scripts diferem apenas na forma como formatam campos de data para o Jira.

| Script | Modo de data | Exemplo de payload |
|---|---|---|
| `weekly_release_updater_jpd.py` | String de date range do JPD | `{"start":"2026-06-22","end":"2026-06-22"}` |
| `weekly_release_updater_jira_software.py` | Data simples do Jira | `2026-06-22` |

As datas de semana da Community são calculadas a partir de `communityFirstPublishedAt`:

| Campo | Cálculo |
|---|---|
| `CF_COMMUNITY_FIRST_PUBLISHED` | Data de `firstPublishedAt` da Community. |
| `CF_COMMUNITY_WEEK_START` | Segunda-feira da mesma semana. |
| `CF_COMMUNITY_WEEK_END` | Domingo da mesma semana. |

Exemplo: se `firstPublishedAt` for `2026-06-24`, então o início da semana será `2026-06-22` e o fim será `2026-06-28`.

## De onde vem a descrição

A descrição da issue é gerada em Atlassian Document Format, usando o payload detalhado mais rico disponível.

O script tenta adicionar estas seções quando existem:

| Seção na descrição Jira | Campo de origem |
|---|---|
| Summary | `summary` |
| Key changes | `keyChanges` |
| Benefits | `benefitsList` |
| How to get started | `getStarted` |
| Reason for change | `reasonForChange` |
| Prepare for change | `prepareForChange` |
| Informed about change | `informedAboutChange` |
| Affected by change | `affectedByChange` |

A descrição também adiciona:

- `Sources: Private, Community` quando as fontes são conhecidas.
- `Atlassian change id: ...` quando existe ID Admin/Community.
- Uma nota quando a busca do detalhe da fonte retorna erro, mas o registro é preservado.

A descrição é atualizada quando uma nova fonte é adicionada a uma issue existente, desde que `UPDATE_DESCRIPTION_ON_SOURCE_ADDED` esteja habilitado.

## Princípios de atualização de campos

O script monta payloads pequenos de atualização. Ele não regrava todos os campos em todas as execuções.

Ele atualiza um campo quando:

- o campo está configurado no script;
- o registro de origem tem um valor desejado;
- o valor atual no Jira está vazio ou diferente;
- ou uma nova fonte apareceu e a issue precisa ser enriquecida.

Campos opcionais são ignorados quando a constante `CF_*` correspondente está vazia.

## Criação de opções

Quando `AUTO_CREATE_FIELD_OPTIONS = True`, o script verifica campos select e multi-select configurados e cria opções faltantes antes de tentar criar ou atualizar issues.

Isso se aplica a campos como Source, Products, Change Status, Change Type, Site Status, Community Status, Community Change Type, Is Delayable e Is Delayed. Community Status deve ser configurado como single-select, enquanto Community Change Type pode continuar como multi-select.

## Log de ações

Ao final de cada execução, o script grava um arquivo JSON de ações contendo:

| Seção | Significado |
|---|---|
| `created` | Issues criadas ou payloads de criação em dry-run. |
| `updated` | Issues atualizadas ou payloads de atualização em dry-run. |
| `skipped` | Registros onde nenhuma criação/atualização era necessária ou criação estava desabilitada. |
| `create_failed` | Registros onde a criação de issue no Jira falhou. |
| `metadata` | Resumo da execução, contagens por fonte, flag de dry-run, timestamp e modo de data. |

O log de ações é útil para auditoria e troubleshooting. Ele não deve conter API tokens ou cookies.
