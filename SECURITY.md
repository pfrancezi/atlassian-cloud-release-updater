# Security Policy

## Reporting a vulnerability

If you believe you have found a security issue, please contact:

```text
contato@idev.com.br
```

Please do not open public GitHub issues for security vulnerabilities.

## Credential handling

This utility is executed locally by the customer.

iDev does not collect, receive, transmit, store, or process Atlassian credentials, API tokens, session cookies, or customer data.

Any credentials used by the script remain under the customer's control and are provided locally at runtime or through local environment variables.

## Do not commit secrets

Do not commit:

- Jira API tokens
- Atlassian Admin cookies
- Atlassian organization IDs, unless you intentionally want them public
- Customer payload files
- Execution logs
- `.env` files
- Generated action output files

The included `.gitignore` blocks the most common local files, but users remain responsible for reviewing changes before committing.
