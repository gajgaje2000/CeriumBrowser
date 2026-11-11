import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mutators.context import MutatorContext
from scripts.mutators.common import translate


def _setup(mock_brave):
    prefs = mock_brave / "browser/brave_profile_prefs.cc"
    prefs.parent.mkdir(parents=True, exist_ok=True)
    prefs.write_text(
        '#include "brave/browser/translate/brave_translate_prefs_migration.h"\n'
        "void RegisterProfilePrefs() {\n"
        "  // Show download prompt by default\n"
        "  registry->SetDefaultPrefValue(prefs::kPromptForDownload, base::Value(true));\n"
        "}\n"
    )

    features = mock_brave / "components/translate/core/common/brave_translate_features.cc"
    features.parent.mkdir(parents=True, exist_ok=True)
    features.write_text(
        "bool UseGoogleTranslateEndpoint() {\n"
        "  return IsBraveTranslateGoAvailable() &&\n"
        "         base::CommandLine::ForCurrentProcess()->HasSwitch(\n"
        "             switches::kBraveTranslateUseGoogleEndpoint);\n"
        "}\n"
    )

    script_cc = mock_brave / "chromium_src/components/translate/core/browser/translate_script.cc"
    script_cc.parent.mkdir(parents=True, exist_ok=True)
    script_cc.write_text(
        "GURL ChromiumTranslateScript::AddHostLocaleToUrl(const GURL& url) {\n"
        "  GURL result = ::translate::AddHostLocaleToUrl(url);\n"
        "  const GURL google_translate_script(kScriptURL);\n"
        "  return result;\n"
        "}\n"
    )

    util_cc = mock_brave / "chromium_src/components/translate/core/common/translate_util.cc"
    util_cc.parent.mkdir(parents=True, exist_ok=True)
    util_cc.write_text(
        '#include "brave/components/translate/core/common/brave_translate_constants.h"\n'
        "\n"
        "#define GetTranslateSecurityOrigin GetTranslateSecurityOrigin_Chromium\n"
        "GURL GetTranslateSecurityOrigin() {\n"
        "  std::string security_origin(kBraveTranslateOrigin);\n"
        "  return GURL(security_origin);\n"
        "}\n"
    )

    js = mock_brave / "components/translate/core/browser/resources/brave_translate.js"
    js.parent.mkdir(parents=True, exist_ok=True)
    js.write_text(
        "const rewriteUrl = (url) => {\n"
        "  try {\n"
        "    let newUrl = new URL(url)\n"
        "    if (newUrl.pathname === '/translate_a/t') {\n"
        "      // useGoogleTranslateEndpoint is predefined by translate_script.cc.\n"
        "      // It's used only for local testing to disable the redirection of\n"
        "      // translation requests.\n"
        "      if (useGoogleTranslateEndpoint) {\n"
        "        // Remove API key\n"
        "        newUrl.searchParams.set('key', '')\n"
        "\n"
        "        // Leave the domain unchanged (translate.googleapis.com).\n"
        "        return newUrl.toString()\n"
        "      }\n"
        "    } else {\n"
    )

    return [prefs, features, script_cc, util_cc, js]


def test_apply(mock_brave):
    prefs, features, script_cc, util_cc, js = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    translate.apply(ctx)

    prefs_txt = prefs.read_text()
    assert '#include "components/translate/core/browser/translate_pref_names.h"' in prefs_txt
    assert "translate::prefs::kOfferTranslateEnabled" in prefs_txt
    assert "return true;" in features.read_text()
    assert "if (translate::UseGoogleTranslateEndpoint())" in script_cc.read_text()
    util_txt = util_cc.read_text()
    assert '#include "brave/components/translate/core/common/brave_translate_features.h"' in util_txt
    assert "return GetTranslateSecurityOrigin_Chromium();" in util_txt
    assert "newUrl.searchParams.delete('key')" in js.read_text()


def test_idempotent(mock_brave):
    files = _setup(mock_brave)
    ctx = MutatorContext(str(mock_brave), strict=True)
    translate.apply(ctx)
    first = [f.read_text() for f in files]
    translate.apply(ctx)
    second = [f.read_text() for f in files]
    assert first == second
