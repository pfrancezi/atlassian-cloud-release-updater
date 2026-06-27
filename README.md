# Atlassian Cloud Release Updater

Português: [README.pt-BR.md](README.pt-BR.md)

Customer-run open-source utility to create and update Jira issues from Atlassian release information.

This repository intentionally does **not** contain a Forge app, Connect app, hosted backend, or Marketplace-installable artifact. The customer runs the code locally in their own environment.

## What this utility does

This utility collects Atlassian release information from two sources and creates or updates issues in a customer-owned Jira or Jira Product Discovery project:

1. **Atlassian Admin private source**, optional and customer-run, using the customer's own `admin.atlassian.com` browser session cookie.
2. **Atlassian Community Release Notes public source**, using the public Community API.

The purpose is to help administrators monitor Atlassian Cloud releases in one Jira-based workspace and compare two perspectives of the same change:

* **Change Status**, from the customer's Atlassian Admin release management view.
* **Community Status**, from Atlassian's public Community Release Notes.

This comparison helps teams identify whether a change announced publicly is already visible, coming soon, rolling out, or generally available for their own Atlassian environment.

## Why use the Atlassian Admin private source?

The Community Release Notes provide a public view of Atlassian product changes, but they do not necessarily reflect how each change appears for a specific customer organization, site, or rollout state.

The Atlassian Admin private source is useful because it can provide the customer-specific release management perspective available in `admin.atlassian.com`, including lifecycle information such as whether a change is coming soon, rolling out, or generally available for that environment.

Using both sources allows teams to keep a local Jira record of Atlassian changes and compare public announcements against the release status visible to their own organization.

## Repository structure

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

## Which script should I use?

Use only one script for each Jira project.

| Project type | Script | Date payload format |
|---|---|---|
| Jira Product Discovery | `scripts/weekly_release_updater_jpd.py` | JSON string date range, for example `{"start":"2026-06-22","end":"2026-06-22"}` |
| Jira Software | `scripts/weekly_release_updater_jira_software.py` | Plain Jira date, for example `2026-06-22` |

## Requirements

- Python 3.10 or newer.
- A Jira Cloud site.
- A Jira project where release issues will be created or updated.
- Jira API token for the account running the script.
- Optional: an Atlassian Admin browser cookie if you want to collect the private Admin source.

Install dependencies:

```bash
pip install -r requirements.txt
```

## Field configuration

Before running the script for real, create the custom fields you want to use and replace the `CF_*` constants near the top of the selected script.

See:

```text
docs/FIELDS_CONFIGURATION.md
```

## Flow and status documentation

For details about the collection flow, matching rules, status behavior, date updates, and Jira description source, see:

```text
docs/FLOW_AND_STATUS.md
```

Portuguese version:

```text
docs/FLUXO_E_STATUS.md
```

All `CF_*` variables are empty by default for public distribution. Optional custom fields are skipped when the corresponding variable is empty.

Example:

```python
CF_SOURCE = "customfield_13005"
CF_ADMIN_ID = "customfield_13214"
```

## Configuration

The scripts are intentionally distributed without customer-specific defaults.

You can provide configuration in three ways:

1. Type the values when prompted.
2. Set environment variables using the names in `env.example`.
3. Edit the `DEFAULT_*` constants locally after cloning the repository.

Recommended for public or Marketplace distribution: keep this repository clean and use local environment variables or a local, uncommitted copy.

Do **not** commit real Jira URLs, emails, API tokens, Atlassian org IDs, cookies, action output files, logs, or customer payloads.

## Environment variables

Copy the example file locally:

```bash
cp env.example .env
```

Then fill your local values. The provided `.gitignore` prevents `.env` from being committed.

On Windows PowerShell, you can also set variables for the current terminal session:

```powershell
$env:JIRA_BASE_URL="https://your-site.atlassian.net"
$env:JIRA_PROJECT_KEY="YOURKEY"
$env:JIRA_ISSUE_TYPE="Task"
$env:JIRA_EMAIL="you@example.com"
$env:JIRA_API_TOKEN="your-api-token"
```

## Run

Start with dry-run mode until the generated payloads look correct.

Jira Product Discovery version:

```bash
python scripts/weekly_release_updater_jpd.py
```

Jira Software version:

```bash
python scripts/weekly_release_updater_jira_software.py
```

The script asks whether to run in dry-run mode.

## Private Admin source

The private Admin source is optional. Leave the Admin cookie blank to skip it.

When used, the cookie is provided locally by the customer at runtime or through the local `ATLASSIAN_ADMIN_COOKIE` environment variable.

This utility does not send the cookie to the vendor. The cookie is used only by the script running in the customer's own environment to call Atlassian's Admin endpoint.

## Security model

The utility is executed locally by the customer.

The vendor does not collect, receive, transmit, store, or process Atlassian credentials, API tokens, session cookies, or customer data.

Any credentials used by the script remain under the customer's control and are provided locally at runtime or through local environment variables.

## Output

The script writes an actions JSON file with created, updated, skipped, and failed actions. It does not include API tokens or cookies.

Output files are ignored by Git through `.gitignore`.


## License

This project is licensed under the MIT License. See `LICENSE`.
