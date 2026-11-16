# Turning on code signing (Azure Artifact Signing)

Signing is wired into `.github/workflows/release.yml` but switched off (`if: ${{ false }}` on two steps). Follow these steps once the Azure Artifact Signing account and the Talaria Software LLC identity validation are complete. Steps 1 and 2 must be done **before any `v*` tag is pushed**.

1. **Create the GitHub environment first.**
   * In the repository, open **Settings › Environments › New environment** and name it `release`.
   * Under **Deployment branches and tags**, choose **Selected branches and tags** and add the tag rule `v*`, with no branches.
   * Do this before any `v*` tag is pushed. If a tag build runs first, GitHub creates `release` automatically **with no rules**.
2. **Azure identity.**
   * Create an app registration, or a user-assigned managed identity.
   * Give it the **Artifact Signing Certificate Profile Signer** role on the certificate profile.
3. **Federated credential (OIDC) on that identity.** No client secret is needed. Use these values:
   * Issuer: `https://token.actions.githubusercontent.com`
   * Subject: `repo:80sFauxstalgia/padsight:environment:release`. This must match exactly; Entra doesn't accept wildcards.
   * Audience: `api://AzureADTokenExchange`
4. **Secrets.**
   * Add these as secrets of the `release` environment: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`.
   * Storing them on the environment keeps them away from other jobs.
5. **Variables.**
   * Add these as repository variables: `ARTIFACT_SIGNING_ENDPOINT` (e.g. `https://<region>.codesigning.azure.net/`), `ARTIFACT_SIGNING_ACCOUNT` and `ARTIFACT_SIGNING_PROFILE`.
6. **Switch the steps on.**
   * In `release.yml`, change `if: ${{ false }}` on **both** signing steps to `if: ${{ startsWith(github.ref, 'refs/tags/v') }}`.
   * Update the README's "Verify your download" note to say releases are signed.
7. **First signed release.** The first `v*` tag build is also the first real run of the environment expression. Check that:
   * the job ran in `release`;
   * `PadSight.exe` shows a valid Talaria Software LLC signature (right-click › Properties › Digital Signatures).

Making the repository public, tags and releases all still need Griff's approval on the Desk (the go-public card).
