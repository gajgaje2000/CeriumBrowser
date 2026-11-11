"""
Shields Feature Mutator (scripts/mutators/common/shields.py)
Enables aggressive shields ad/tracker blocking and 1p blocking by default.
"""

from scripts.mutators.context import MutatorContext


def apply(ctx: MutatorContext):
    ctx.replace_in_file(
        "components/brave_shields/core/common/features.cc",
        "BASE_FEATURE(kBraveAdblockDefault1pBlocking, base::FEATURE_DISABLED_BY_DEFAULT);",
        "BASE_FEATURE(kBraveAdblockDefault1pBlocking, base::FEATURE_ENABLED_BY_DEFAULT);",
    )

    ctx.replace_in_file(
        "components/brave_shields/core/common/brave_shields_settings_values.h",
        "/*default_value=*/ControlType::BLOCK_THIRD_PARTY>;",
        "/*default_value=*/ControlType::BLOCK>;",
    )

    ctx.replace_in_file(
        "browser/brave_browser_process_impl.cc",
        "  // eagerly initialize for component updater\n  https_upgrade_exceptions_service();",
        "  // eagerly initialize for component updater\n  ad_block_service();\n  https_upgrade_exceptions_service();",
        check_token="ad_block_service();\n  https_upgrade_exceptions_service();",
    )

    ctx.replace_in_file(
        "components/brave_shields/core/browser/ad_block_filters_provider_manager.cc",
        "  // All startup providers are initialized so we can safely consume the startup\n"
        "  // notification. The next call to OnChanged will trigger NotifyObservers\n"
        "  if (MaybeConsumeEngineStartupChangeNotification(is_for_default_engine)) {\n"
        "    return;\n"
        "  }\n\n"
        "  NotifyObservers(is_for_default_engine);",
        "  MaybeConsumeEngineStartupChangeNotification(is_for_default_engine);\n"
        "  NotifyObservers(is_for_default_engine);",
        check_token="MaybeConsumeEngineStartupChangeNotification(is_for_default_engine);\n  NotifyObservers(is_for_default_engine);",
    )
