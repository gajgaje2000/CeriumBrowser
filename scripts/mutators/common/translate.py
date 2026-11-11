"""
Page Translation Mutator (scripts/mutators/common/translate.py)
Configures translation to be disabled by default for privacy (opt-in in Settings),
and ensures that when enabled, translation requests route cleanly to Google Translate
without Brave's proprietary service key authentication failures (403 Forbidden).
"""

from scripts.mutators.context import MutatorContext


def apply(ctx: MutatorContext):
    # 1. Ensure translate_pref_names.h is included unconditionally across all platforms
    ctx.replace_in_file(
        "browser/brave_profile_prefs.cc",
        '#include "brave/browser/translate/brave_translate_prefs_migration.h"',
        '#include "brave/browser/translate/brave_translate_prefs_migration.h"\n#include "components/translate/core/browser/translate_pref_names.h"',
    )

    # 2. Disable translation offer by default out-of-the-box in brave_profile_prefs.cc
    ctx.replace_in_file(
        "browser/brave_profile_prefs.cc",
        "  // Show download prompt by default\n  registry->SetDefaultPrefValue(prefs::kPromptForDownload, base::Value(true));",
        "  // Show download prompt by default\n  registry->SetDefaultPrefValue(prefs::kPromptForDownload, base::Value(true));\n\n  // Disable translation offer prompts by default for privacy (opt-in in Settings)\n  registry->SetDefaultPrefValue(translate::prefs::kOfferTranslateEnabled,\n                                base::Value(false));",
    )

    # 2. Return true for UseGoogleTranslateEndpoint() in brave_translate_features.cc
    # This prevents brave_translate.js from redirecting to translate.brave.com with key=no-key
    ctx.replace_in_file(
        "components/translate/core/common/brave_translate_features.cc",
        """bool UseGoogleTranslateEndpoint() {
  return IsBraveTranslateGoAvailable() &&
         base::CommandLine::ForCurrentProcess()->HasSwitch(
             switches::kBraveTranslateUseGoogleEndpoint);
}""",
        """bool UseGoogleTranslateEndpoint() {
  return true;
}""",
    )

    # 3. Allow Google Translate script URL in translate_script.cc
    ctx.replace_in_file(
        "chromium_src/components/translate/core/browser/translate_script.cc",
        """GURL ChromiumTranslateScript::AddHostLocaleToUrl(const GURL& url) {
  GURL result = ::translate::AddHostLocaleToUrl(url);
  const GURL google_translate_script(kScriptURL);""",
        """GURL ChromiumTranslateScript::AddHostLocaleToUrl(const GURL& url) {
  GURL result = ::translate::AddHostLocaleToUrl(url);
  if (translate::UseGoogleTranslateEndpoint()) {
    return result;
  }
  const GURL google_translate_script(kScriptURL);""",
    )

    # 4. Allow Google Translate security origin in translate_util.cc
    ctx.replace_in_file(
        "chromium_src/components/translate/core/common/translate_util.cc",
        """#include "brave/components/translate/core/common/brave_translate_constants.h"

#define GetTranslateSecurityOrigin GetTranslateSecurityOrigin_Chromium""",
        """#include "brave/components/translate/core/common/brave_translate_constants.h"
#include "brave/components/translate/core/common/brave_translate_features.h"

#define GetTranslateSecurityOrigin GetTranslateSecurityOrigin_Chromium""",
    )

    ctx.replace_in_file(
        "chromium_src/components/translate/core/common/translate_util.cc",
        """GURL GetTranslateSecurityOrigin() {
  std::string security_origin(kBraveTranslateOrigin);""",
        """GURL GetTranslateSecurityOrigin() {
  if (UseGoogleTranslateEndpoint()) {
    return GetTranslateSecurityOrigin_Chromium();
  }
  std::string security_origin(kBraveTranslateOrigin);""",
    )

    # 5. Prevent brave_translate.js from rewriting static assets to nonexistent paths on Google endpoint
    ctx.replace_in_file(
        "components/translate/core/browser/resources/brave_translate.js",
        """const rewriteUrl = (url) => {
  try {
    let newUrl = new URL(url)
    if (newUrl.pathname === '/translate_a/t') {
      // useGoogleTranslateEndpoint is predefined by translate_script.cc.
      // It's used only for local testing to disable the redirection of
      // translation requests.
      if (useGoogleTranslateEndpoint) {
        // Remove API key
        newUrl.searchParams.set('key', '')

        // Leave the domain unchanged (translate.googleapis.com).
        return newUrl.toString()
      }
    } else {""",
        """const rewriteUrl = (url) => {
  try {
    let newUrl = new URL(url)
    if (useGoogleTranslateEndpoint) {
      newUrl.searchParams.delete('key')
      return newUrl.toString()
    }
    if (newUrl.pathname === '/translate_a/t') {
    } else {""",
    )
