"""
Sync Defaults & Notice Mutator (scripts/mutators/common/sync.py)
1. Neutralizes the default sync endpoint in brave_sync to prevent connecting to official servers without explicit configuration.
2. Injects a self-hosting requirement notice and brave://flags instruction into the Desktop Sync Setup screen.
"""

from scripts.mutators.context import MutatorContext


def apply(ctx: MutatorContext):
    # 1. Neutralize default sync endpoint so unconfigured builds do not connect to official Brave sync servers
    ctx.replace_in_file(
        "components/brave_sync/BUILD.gn",
        'brave_sync_endpoint = "https://sync-v2.brave.com/v2"',
        'brave_sync_endpoint = "https://127.0.0.1:8295/v2"',
    )

    # 2. Add self-hosted sync notice banner to Desktop Sync Setup page
    old_desktop_setup = """    <h1>$i18n{braveSyncSetupTitle}</h1>
    <p>$i18n{braveSyncSetupSubtitle}</p>"""

    new_desktop_setup = """    <h1>$i18n{braveSyncSetupTitle}</h1>
    <p>$i18n{braveSyncSetupSubtitle}</p>
    <div class="sync-self-host-notice" style="margin: 12px 0 16px 0; padding: 12px; background: rgba(255, 165, 0, 0.1); border-left: 4px solid #ff9800; border-radius: 4px; font-size: 13px; line-height: 1.5;">
      <strong>Self-Hosted Sync Required:</strong> Cerium does not operate a centralized sync server. Host your own instance (<a href="https://github.com/brave/go-sync" target="_blank" rel="noopener noreferrer">https://github.com/brave/go-sync</a>) and configure the server URL in <code>brave://flags</code> (search for <strong>#brave-override-sync-server-url</strong>).
    </div>"""

    ctx.replace_in_file(
        "browser/resources/settings/brave_sync_page/brave_sync_setup.html",
        old_desktop_setup,
        new_desktop_setup,
    )
