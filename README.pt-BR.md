# Atlassian Cloud Release Updater

Utilitário open-source, executado pelo próprio cliente, para criar e atualizar issues no Jira a partir de informações de releases da Atlassian.

Este repositório **não** contém um app Forge, app Connect, backend hospedado ou artefato instalável pelo Marketplace. O cliente executa o código localmente, no próprio ambiente.

English version: [README.md](README.md)

## O que esta ferramenta faz

Esta ferramenta coleta informações de releases da Atlassian a partir de duas fontes e cria ou atualiza issues em um projeto Jira ou Jira Product Discovery pertencente ao próprio cliente:

1. **Fonte privada do Atlassian Admin**, opcional e executada pelo próprio cliente, usando o cookie da sessão de navegador do próprio cliente em `admin.atlassian.com`.
2. **Fonte pública Atlassian Community Release Notes**, usando a API pública da Community.

O objetivo é ajudar administradores a monitorar releases do Atlassian Cloud em um workspace baseado em Jira e comparar duas perspectivas da mesma mudança:

* **Change Status**, vindo da visão de release management do Atlassian Admin do cliente.
* **Community Status**, vindo das Atlassian Community Release Notes públicas.

Essa comparação ajuda os times a identificar se uma mudança anunciada publicamente já está visível, prevista, em rollout ou geralmente disponível para o próprio ambiente Atlassian.

## Por que usar a fonte privada do Atlassian Admin?

As Community Release Notes fornecem uma visão pública das mudanças nos produtos Atlassian, mas não refletem necessariamente como cada mudança aparece para uma organização, site ou estado de rollout específico de um cliente.

A fonte privada do Atlassian Admin é útil porque pode fornecer a perspectiva de release management específica do cliente disponível em `admin.atlassian.com`, incluindo informações de ciclo de vida como se uma mudança está prevista, em rollout ou geralmente disponível para aquele ambiente.

Usar as duas fontes permite que os times mantenham um registro local das mudanças Atlassian no Jira e comparem os anúncios públicos com o status de release visível para a própria organização.


## Estrutura do repositório

```text
atlassian-cloud-release-updater/
├─ README.md
├─ README.pt-BR.md
├─ LICENSE
├─ SECURITY.md
├─ CHANGELOG.md
├─ .gitignore
├─ env.example
├─ requirements.txt
├─ docs/
│  ├─ FIELDS_CONFIGURATION.md
│  ├─ FLOW_AND_STATUS.md
│  └─ FLUXO_E_STATUS.md
└─ scripts/
   ├─ weekly_release_updater_jpd.py
   └─ weekly_release_updater_jira_software.py
```

## Qual script usar?

Use apenas um script por projeto Jira.

| Tipo de projeto | Script | Formato dos campos de data |
|---|---|---|
| Jira Product Discovery | `scripts/weekly_release_updater_jpd.py` | String JSON de date range, por exemplo `{"start":"2026-06-22","end":"2026-06-22"}` |
| Jira Software | `scripts/weekly_release_updater_jira_software.py` | Data simples do Jira, por exemplo `2026-06-22` |

## Requisitos

- Python 3.10 ou superior.
- Um site Jira Cloud.
- Um projeto Jira onde as issues de releases serão criadas ou atualizadas.
- API token Jira da conta que executará o script.
- Opcional: cookie de sessão do Atlassian Admin, caso você queira coletar a fonte privada.

Instale as dependências:

```bash
pip install -r requirements.txt
```

## Configuração dos campos

Antes de rodar o script de verdade, crie os campos customizados que deseja usar e substitua as constantes `CF_*` no início do script escolhido.

Veja:

```text
docs/FIELDS_CONFIGURATION.md
```

Todas as variáveis `CF_*` ficam vazias por padrão para distribuição pública. Campos opcionais são ignorados quando a variável correspondente está vazia.

Exemplo:

```python
CF_SOURCE = "customfield_13005"
CF_ADMIN_ID = "customfield_13214"
```

## Documentação do fluxo

Para entender como as fontes são coletadas, como os registros são combinados, como os status funcionam e de onde a descrição da issue é montada, veja:

```text
docs/FLUXO_E_STATUS.md
```

Versão em inglês:

```text
docs/FLOW_AND_STATUS.md
```

## Configuração local

Os scripts são distribuídos sem valores específicos de cliente.

Você pode configurar de três formas:

1. Digitar os valores quando o script perguntar.
2. Usar variáveis de ambiente com os nomes indicados em `env.example`.
3. Editar localmente as constantes `DEFAULT_*` depois de clonar o repositório.

Para distribuição pública ou Marketplace, mantenha o repositório limpo e use variáveis de ambiente ou uma cópia local não versionada.

Não faça commit de URLs reais de clientes, emails, API tokens, cookies, arquivos de saída, logs ou payloads de cliente.

## Variáveis de ambiente

Copie o arquivo de exemplo localmente:

```bash
cp env.example .env
```

Depois preencha os valores locais. O `.gitignore` impede que `.env` seja enviado para o GitHub.

No Windows PowerShell, você também pode definir variáveis para a sessão atual do terminal:

```powershell
$env:JIRA_BASE_URL="https://your-site.atlassian.net"
$env:JIRA_PROJECT_KEY="YOURKEY"
$env:JIRA_ISSUE_TYPE="Task"
$env:JIRA_EMAIL="you@example.com"
$env:JIRA_API_TOKEN="your-api-token"
```

## Execução

Comece com dry-run até validar os payloads gerados.

Versão Jira Product Discovery:

```bash
python scripts/weekly_release_updater_jpd.py
```

Versão Jira Software:

```bash
python scripts/weekly_release_updater_jira_software.py
```

O script pergunta se deve executar em modo dry-run.

## Fonte privada do Atlassian Admin

A fonte privada é opcional. Deixe o cookie em branco para ignorá-la.

Quando usado, o cookie é informado localmente pelo cliente em tempo de execução ou pela variável local `ATLASSIAN_ADMIN_COOKIE`.

Este utilitário não envia o cookie para a iDev ou qualquer backend de fornecedor. O cookie é usado apenas pelo script em execução no ambiente do próprio cliente para chamar o endpoint da Atlassian.

## Modelo de segurança

O utilitário é executado localmente pelo cliente.

O fornecedor não coleta, recebe, transmite, armazena ou processa credenciais Atlassian, API tokens, cookies de sessão ou dados de cliente.

Qualquer credencial usada pelo script permanece sob controle do cliente e é informada localmente em tempo de execução ou por variáveis de ambiente locais.

## Saída

O script grava um arquivo JSON de ações com itens criados, atualizados, ignorados e falhas de criação. Esse arquivo não inclui API tokens ou cookies.

Arquivos de saída são ignorados pelo Git via `.gitignore`.


## Licença

Este projeto está licenciado sob a licença MIT. Veja `LICENSE`.
