#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BRAVE_DIR="${1:-}"
SRC_DIR="${2:-}"
if [[ -z "${BRAVE_DIR}" ]]; then
  echo "Usage: $0 <path-to-brave-core> [path-to-chromium-src]" >&2
  exit 1
fi

echo "Applying Cerium Vector & Raster Branding Assets..."

# 1. Overlay Android vector drawables into brave-res/drawable/, res/drawable/, and first_run/
mkdir -p "${BRAVE_DIR}/android/java/brave-res/drawable"
mkdir -p "${BRAVE_DIR}/android/java/res/drawable"
mkdir -p "${BRAVE_DIR}/browser/first_run/android/java/res/drawable"

XML_COUNT=0
copy_static_xml() {
  local src="$1"
  local dst="$2"
  if [[ ! -s "${src}" ]]; then
    echo "ERROR: Missing or empty static branding XML source: ${src}" >&2
    exit 1
  fi
  cp -f "${src}" "${dst}"
  if [[ ! -s "${dst}" ]]; then
    echo "ERROR: Static branding XML copy produced empty or missing file: ${dst}" >&2
    exit 1
  fi
  XML_COUNT=$((XML_COUNT + 1))
}

BRAVE_RES_VECTORS=(
  "ic_brave_logo.xml"
  "ic_brave.xml"
  "ic_brave_36.xml"
  "ic_channel_brave.xml"
  "ic_brave_notification.xml"
)

for vec in "${BRAVE_RES_VECTORS[@]}"; do
  gn_vec="java/brave-res/drawable/${vec}"
  if [[ -f "${BRAVE_DIR}/android/BUILD.gn" ]] && ! grep -Fq "\"${gn_vec}\"" "${BRAVE_DIR}/android/BUILD.gn" 2>/dev/null; then
    continue
  fi
  copy_static_xml "${REPO_ROOT}/branding/android/drawable/${vec}" "${BRAVE_DIR}/android/java/brave-res/drawable/${vec}"
  echo " [OK] Copied ${vec} to android/java/brave-res/drawable/"
done

copy_static_xml "${REPO_ROOT}/branding/android/drawable/chrome_logo_on_circular_background.xml" \
                "${BRAVE_DIR}/android/java/res/drawable/chrome_logo_on_circular_background.xml"
echo " [OK] Copied chrome_logo_on_circular_background.xml to android/java/res/drawable/"

FIRST_RUN_VECTORS=(
  "ic_brave_splash.xml"
  "ic_brave_brand.xml"
  "onboarding_illustration.xml"
)

for vec in "${FIRST_RUN_VECTORS[@]}"; do
  copy_static_xml "${REPO_ROOT}/branding/android/drawable/${vec}" "${BRAVE_DIR}/browser/first_run/android/java/res/drawable/${vec}"
  echo " [OK] Copied ${vec} to browser/first_run/android/java/res/drawable/"
done

# 2. Overlay Android adaptive & themed vector icons into app/theme/brave/android/res_brave_base/ (and default/origin variants)
for theme_root in "${BRAVE_DIR}/app/theme/brave/android" "${BRAVE_DIR}/app/theme/brave_origin/android"; do
  for base_sub in "res_brave_base" "res_brave_default_base"; do
    target_base="${theme_root}/${base_sub}"
    mkdir -p "${target_base}/drawable" "${target_base}/drawable-night" "${target_base}/mipmap-anydpi-v26" "${target_base}/mipmap-nodpi"
    copy_static_xml "${REPO_ROOT}/branding/android/res_brave_base/drawable/themed_app_icon.xml" "${target_base}/drawable/themed_app_icon.xml"
    copy_static_xml "${REPO_ROOT}/branding/android/res_brave_base/drawable-night/themed_app_icon.xml" "${target_base}/drawable-night/themed_app_icon.xml"
    for xml_src in "${REPO_ROOT}/branding/android/res_brave_base/mipmap-anydpi-v26/"*.xml; do
      copy_static_xml "${xml_src}" "${target_base}/mipmap-anydpi-v26/$(basename "${xml_src}")"
    done
    for xml_src in "${REPO_ROOT}/branding/android/res_brave_base/mipmap-nodpi/"*.xml; do
      copy_static_xml "${xml_src}" "${target_base}/mipmap-nodpi/$(basename "${xml_src}")"
    done
  done
done
echo " [OK] Overlaid adaptive app_icon.xml, layered_app_icon.xml, and themed_app_icon.xml into res_brave_base/."

# 3. Overlay Shields toolbar vector drawables into app/theme/brave/android/shields_drawables/
THEME_ANDROID="${BRAVE_DIR}/app/theme/brave/android"
mkdir -p "${THEME_ANDROID}/shields_drawables"
for xml_src in "${REPO_ROOT}/branding/android/shields_drawables/"*.xml; do
  copy_static_xml "${xml_src}" "${THEME_ANDROID}/shields_drawables/$(basename "${xml_src}")"
  if [[ -d "${BRAVE_DIR}/node_modules/@brave/leo/tokens/android/drawable" ]]; then
    copy_static_xml "${xml_src}" "${BRAVE_DIR}/node_modules/@brave/leo/tokens/android/drawable/$(basename "${xml_src}")"
  fi
done
if [[ ${XML_COUNT} -lt 32 ]]; then
  echo "ERROR: Expected at least 32 static XML overlays, but copied ${XML_COUNT}." >&2
  exit 1
fi
echo " [OK] Overlaid Shields vector drawables into app/theme/brave/android/shields_drawables/ (${XML_COUNT} total XML files copied)."

# 4. Copy all static pre-rendered raster PNG and SVG logos from branding/brave-core-static/ into BRAVE_DIR
STATIC_DIR="${REPO_ROOT}/branding/brave-core-static"
if [[ ! -d "${STATIC_DIR}" ]]; then
  echo "ERROR: Missing static branding directory at ${STATIC_DIR}" >&2
  exit 1
fi

PNG_COUNT=0
SVG_COUNT=0
ICO_COUNT=0
while IFS= read -r -d '' src_file; do
  rel_path="${src_file#${STATIC_DIR}/}"
  # For resources destined for android/java/brave-res/, dynamically verify against
  # android/BUILD.gn to avoid prepare_resources.py failing on unlisted sources
  if [[ "${rel_path}" == android/java/brave-res/* ]]; then
    gn_entry="${rel_path#android/}"
    if [[ -f "${BRAVE_DIR}/android/BUILD.gn" ]] && ! grep -Fq "\"${gn_entry}\"" "${BRAVE_DIR}/android/BUILD.gn" 2>/dev/null; then
      continue
    fi
  fi
  dest_file="${BRAVE_DIR}/${rel_path}"
  mkdir -p "$(dirname "${dest_file}")"
  cp -f "${src_file}" "${dest_file}"
  if [[ ! -s "${dest_file}" ]]; then
    echo "ERROR: Static branding file copy produced empty or missing file: ${dest_file}" >&2
    exit 1
  fi
  if [[ "${rel_path}" == *.png ]]; then
    PNG_COUNT=$((PNG_COUNT + 1))
  elif [[ "${rel_path}" == *.svg ]]; then
    SVG_COUNT=$((SVG_COUNT + 1))
  elif [[ "${rel_path}" == *.ico ]]; then
    ICO_COUNT=$((ICO_COUNT + 1))
  fi
done < <(find "${STATIC_DIR}" -type f \( -name "*.png" -o -name "*.svg" -o -name "*.ico" \) -print0 | sort -z)

if [[ ${PNG_COUNT} -lt 146 || ${PNG_COUNT} -gt 156 || ${SVG_COUNT} -ne 10 || ${ICO_COUNT} -ne 26 ]]; then
  echo "ERROR: Expected between 146 and 156 static PNGs, 10 static SVGs, and 26 static ICOs in ${STATIC_DIR}, but copied ${PNG_COUNT} PNGs, ${SVG_COUNT} SVGs, and ${ICO_COUNT} ICOs." >&2
  exit 1
fi
echo " [OK] Copied ${PNG_COUNT} static raster PNG logos, ${SVG_COUNT} static SVG logos, and ${ICO_COUNT} static Windows ICO logos into brave-core."

# 4b. Defense-in-depth: Mirror desktop raster PNG logos, ICOs, SVGs, and win/tiles/ to brave_origin if present
if [[ -f "${BRAVE_DIR}/app/theme/brave_origin/BRANDING" ]]; then
  for png_file in "${STATIC_DIR}/app/theme/brave/"product_logo_*.png; do
    if [[ -f "${png_file}" ]]; then
      cp -f "${png_file}" "${BRAVE_DIR}/app/theme/brave_origin/$(basename "${png_file}")"
    fi
  done
  for variant in beta dev development nightly; do
    for sz in 128 256 64 48 24; do
      [[ -f "${BRAVE_DIR}/app/theme/brave_origin/product_logo_${sz}.png" ]] && \
        cp -f "${BRAVE_DIR}/app/theme/brave_origin/product_logo_${sz}.png" "${BRAVE_DIR}/app/theme/brave_origin/product_logo_${sz}_${variant}.png" 2>/dev/null || true
    done
  done
  if [[ -d "${STATIC_DIR}/app/theme/brave/win" ]]; then
    mkdir -p "${BRAVE_DIR}/app/theme/brave_origin/win/tiles"
    cp -f "${STATIC_DIR}/app/theme/brave/win/"*.ico "${BRAVE_DIR}/app/theme/brave_origin/win/" 2>/dev/null || true
    cp -f "${STATIC_DIR}/app/theme/brave/win/tiles/"* "${BRAVE_DIR}/app/theme/brave_origin/win/tiles/" 2>/dev/null || true
  fi
  if [[ -d "${STATIC_DIR}/app/theme/brave/linux" ]]; then
    mkdir -p "${BRAVE_DIR}/app/theme/brave_origin/linux"
    cp -f "${STATIC_DIR}/app/theme/brave/linux/"* "${BRAVE_DIR}/app/theme/brave_origin/linux/" 2>/dev/null || true
    for variant in beta dev development nightly; do
      for sz in 128 256 64 48 24; do
        [[ -f "${BRAVE_DIR}/app/theme/brave_origin/linux/product_logo_${sz}.png" ]] && \
          cp -f "${BRAVE_DIR}/app/theme/brave_origin/linux/product_logo_${sz}.png" "${BRAVE_DIR}/app/theme/brave_origin/linux/product_logo_${sz}_${variant}.png" 2>/dev/null || true
      done
    done
  fi
  cp -f "${STATIC_DIR}/app/theme/brave/product_logo.svg" "${BRAVE_DIR}/app/theme/brave_origin/product_logo.svg" 2>/dev/null || true
  cp -f "${STATIC_DIR}/app/theme/brave/product_logo_animation.svg" "${BRAVE_DIR}/app/theme/brave_origin/product_logo_animation.svg" 2>/dev/null || true
  cp -f "${STATIC_DIR}/app/theme/brave/password_manager_logo.svg" "${BRAVE_DIR}/app/theme/brave_origin/password_manager_logo.svg" 2>/dev/null || true
  for scale in default_100_percent default_200_percent; do
    scale_dir="${BRAVE_DIR}/app/theme/${scale}/brave_origin"
    if [[ -d "${scale_dir}" ]]; then
      logo32="${scale_dir}/product_logo_32.png"
      if [[ -f "${logo32}" ]]; then
        for variant in beta dev development nightly; do
          cp -f "${logo32}" "${scale_dir}/product_logo_32_${variant}.png" 2>/dev/null || true
        done
      fi
      logo16="${scale_dir}/product_logo_16.png"
      if [[ -f "${logo16}" ]]; then
        for variant in beta dev development nightly; do
          cp -f "${logo16}" "${scale_dir}/product_logo_16_${variant}.png" 2>/dev/null || true
        done
      fi
      if [[ -d "${scale_dir}/linux" ]]; then
        for variant in beta dev development nightly; do
          [[ -f "${scale_dir}/linux/product_logo_32.png" ]] && cp -f "${scale_dir}/linux/product_logo_32.png" "${scale_dir}/linux/product_logo_32_${variant}.png" 2>/dev/null || true
          [[ -f "${scale_dir}/linux/product_logo_16.png" ]] && cp -f "${scale_dir}/linux/product_logo_16.png" "${scale_dir}/linux/product_logo_16_${variant}.png" 2>/dev/null || true
        done
      fi
    fi
  done
  echo " [OK] Mirrored desktop raster branding assets to app/theme/brave_origin/"
fi

# 4c. Defense-in-depth: Overwrite development/beta/nightly desktop logos and avatar PNGs if present
# (Only overwrite files that already exist in target to preserve static count assertions in test_branding.py)
for scale in default_100_percent default_200_percent; do
  scale_dir="${BRAVE_DIR}/app/theme/${scale}/brave"
  if [[ -d "${scale_dir}" ]]; then
    for variant in beta dev development nightly; do
      [[ -f "${scale_dir}/product_logo_32_${variant}.png" && -f "${scale_dir}/product_logo_32.png" ]] && \
        cp -f "${scale_dir}/product_logo_32.png" "${scale_dir}/product_logo_32_${variant}.png" || true
      [[ -f "${scale_dir}/product_logo_16_${variant}.png" && -f "${scale_dir}/product_logo_16.png" ]] && \
        cp -f "${scale_dir}/product_logo_16.png" "${scale_dir}/product_logo_16_${variant}.png" || true
      [[ -f "${scale_dir}/linux/product_logo_32_${variant}.png" && -f "${scale_dir}/linux/product_logo_32.png" ]] && \
        cp -f "${scale_dir}/linux/product_logo_32.png" "${scale_dir}/linux/product_logo_32_${variant}.png" || true
      [[ -f "${scale_dir}/linux/product_logo_16_${variant}.png" && -f "${scale_dir}/linux/product_logo_16.png" ]] && \
        cp -f "${scale_dir}/linux/product_logo_16.png" "${scale_dir}/linux/product_logo_16_${variant}.png" || true
    done
    [[ -f "${scale_dir}/product_brave_leo.png" && -f "${scale_dir}/product_logo_32.png" ]] && \
      cp -f "${scale_dir}/product_logo_32.png" "${scale_dir}/product_brave_leo.png" || true
  fi
done

brave_theme_dir="${BRAVE_DIR}/app/theme/brave"
if [[ -d "${brave_theme_dir}" ]]; then
  for variant in beta dev development nightly; do
    [[ -f "${brave_theme_dir}/product_logo_128_${variant}.png" && -f "${brave_theme_dir}/product_logo_128.png" ]] && \
      cp -f "${brave_theme_dir}/product_logo_128.png" "${brave_theme_dir}/product_logo_128_${variant}.png" || true
    [[ -f "${brave_theme_dir}/linux/product_logo_128_${variant}.png" && -f "${brave_theme_dir}/linux/product_logo_128.png" ]] && \
      cp -f "${brave_theme_dir}/linux/product_logo_128.png" "${brave_theme_dir}/linux/product_logo_128_${variant}.png" || true
  done
fi

avatar_dir="${BRAVE_DIR}/app/theme/default_100_percent/common/avatars"
logo_32="${BRAVE_DIR}/app/theme/default_100_percent/brave/product_logo_32.png"
if [[ -d "${avatar_dir}" && -f "${logo_32}" ]]; then
  for shape in bonbon edgy gleam oval paladin; do
    for kind in brave rewards; do
      target_avatar="${avatar_dir}/avatar_${shape}_${kind}.png"
      if [[ -f "${target_avatar}" ]]; then
        cp -f "${logo_32}" "${target_avatar}"
      fi
    done
  done
fi

# 4d. Overwrite Leo WebUI SVGs in node_modules/@brave/leo/icons with Cerium SVG
leo_icons_dir="${BRAVE_DIR}/node_modules/@brave/leo/icons"
cerium_svg="${REPO_ROOT}/branding/logo.svg"
if [[ -d "${leo_icons_dir}" && -f "${cerium_svg}" ]]; then
  for icon_name in \
    social-brave-release-favicon-fullheight-color.svg \
    social-brave-beta-favicon-fullheight-color.svg \
    social-brave-dev-favicon-fullheight-color.svg \
    social-brave-nightly-favicon-fullheight-color.svg \
    social-brave-monochrome-favicon-fullheight-color.svg \
    social-brave-carved-favicon-fullheight.svg \
    social-brave-outline-favicon-fullheight.svg \
    social-brave-newface-favicon-fullheight.svg \
    social-brave-ask-favicon-fullheight-color.svg \
    brave-icon-release-color.svg \
    brave-icon-beta-color.svg \
    brave-icon-dev-color.svg \
    brave-icon-nightly-color.svg \
    brave-icon-monochrome.svg \
    brave-icon-outline.svg \
    brave-icon-only-face.svg \
    brave-icon-only-face-disabled.svg \
    brave-icon-search-color.svg \
    brave-icon-search.svg \
    brave-origin-release-color.svg \
    brave-origin-beta-color.svg \
    brave-origin-dev-color.svg \
    brave-origin-nightly-color.svg \
    product-origin.svg \
    origin-color.svg \
    product-brave-leo.svg \
    product-brave-talk.svg \
    product-brave-wallet.svg \
    product-brave-news.svg \
    pwa-brave-install-color.svg; do
    if [[ -f "${leo_icons_dir}/${icon_name}" ]]; then
      cp -f "${cerium_svg}" "${leo_icons_dir}/${icon_name}"
    fi
  done
  echo " [OK] Mirrored Cerium logo to node_modules/@brave/leo/icons"
fi

# 4e. Deploy Cerium C++ and Leo vector icons (.icon)
VECTOR_ICON_SRC="${REPO_ROOT}/branding/vector_icons/product.icon"
VECTOR_ICON_MONO="${REPO_ROOT}/branding/vector_icons/product_monochrome.icon"
VECTOR_ICON_APP_MENU_COLOR="${REPO_ROOT}/branding/vector_icons/app_menu_color.icon"
VECTOR_ICON_APP_MENU_OUTLINE="${REPO_ROOT}/branding/vector_icons/app_menu_outline.icon"
if [[ -f "${VECTOR_ICON_SRC}" ]]; then
  for brand in brave brave_origin; do
    vdir="${BRAVE_DIR}/components/vector_icons/${brand}"
    if [[ -d "${vdir}" ]]; then
      cp -f "${VECTOR_ICON_SRC}" "${vdir}/product.icon"
      cp -f "${VECTOR_ICON_SRC}" "${vdir}/product_refresh.icon"
      echo " [OK] Overlaid Cerium vector icons in components/vector_icons/${brand}/"
    fi
    odir="${BRAVE_DIR}/components/omnibox/browser/vector_icons/${brand}"
    if [[ -d "${odir}" ]]; then
      cp -f "${VECTOR_ICON_SRC}" "${odir}/product.icon"
      cp -f "${VECTOR_ICON_SRC}" "${odir}/product_chrome_refresh.icon"
      echo " [OK] Overlaid Cerium vector icons in components/omnibox/browser/vector_icons/${brand}/"
    fi
  done

  if [[ -d "${BRAVE_DIR}/components/vector_icons" ]]; then
    [[ -f "${VECTOR_ICON_APP_MENU_COLOR}" ]] && cp -f "${VECTOR_ICON_APP_MENU_COLOR}" "${BRAVE_DIR}/components/vector_icons/app_menu_color.icon" || true
    [[ -f "${VECTOR_ICON_APP_MENU_OUTLINE}" ]] && cp -f "${VECTOR_ICON_APP_MENU_OUTLINE}" "${BRAVE_DIR}/components/vector_icons/app_menu_outline.icon" || true
    echo " [OK] Overlaid Cerium app menu vector icons in components/vector_icons/"
  fi

  leo_skia="${BRAVE_DIR}/node_modules/@brave/leo/icons-skia"
  if [[ -d "${leo_skia}" ]]; then
    for icon_name in \
      leo_brave_origin_release_color.icon \
      leo_brave_origin_beta_color.icon \
      leo_brave_origin_dev_color.icon \
      leo_brave_origin_nightly_color.icon \
      leo_brave_icon_release_color.icon \
      leo_brave_icon_beta_color.icon \
      leo_brave_icon_dev_color.icon \
      leo_brave_icon_nightly_color.icon \
      leo_product_origin.icon \
      leo_origin_color.icon \
      leo_social_brave_release_favicon_fullheight_color.icon \
      leo_social_brave_beta_favicon_fullheight_color.icon \
      leo_social_brave_dev_favicon_fullheight_color.icon \
      leo_social_brave_nightly_favicon_fullheight_color.icon \
      leo_pwa_brave_install_color.icon \
      leo_brave_player.icon \
      leo_brave_search_big_color.icon \
      leo_product_brave_leo.icon \
      leo_product_brave_talk.icon \
      leo_product_brave_wallet.icon \
      leo_product_brave_news.icon; do
      [[ -f "${leo_skia}/${icon_name}" ]] && cp -f "${VECTOR_ICON_SRC}" "${leo_skia}/${icon_name}" || true
    done
    for icon_name in \
      leo_brave_icon_monochrome.icon \
      leo_brave_icon_only_face.icon \
      leo_brave_icon_only_face_disabled.icon \
      leo_brave_icon_outline.icon \
      leo_social_brave_monochrome_favicon_fullheight_color.icon \
      leo_social_brave_outline_favicon_fullheight.icon \
      leo_social_brave_newface_favicon_fullheight.icon \
      leo_brave_ask.icon \
      leo_brave_icon_search.icon \
      leo_news_brave.icon; do
      [[ -f "${leo_skia}/${icon_name}" ]] && cp -f "${VECTOR_ICON_MONO}" "${leo_skia}/${icon_name}" || true
    done
    echo " [OK] Overlaid Cerium Skia vector icons in node_modules/@brave/leo/icons-skia"
  fi
fi

# 5. Prevent java_resources failure by removing any misplaced branding folders in brave-res
rm -rf "${BRAVE_DIR}/android/java/brave-res/mipmap-"* \
       "${BRAVE_DIR}/android/java/brave-res/res_brave"* \
       "${BRAVE_DIR}/android/java/brave-res/shields_drawables" 2>/dev/null || true

# 6. Clean up any stale or unlisted rasterized files in density folders
for density in mdpi hdpi xhdpi xxhdpi xxxhdpi; do
  density_dir="${BRAVE_DIR}/android/java/brave-res/drawable-${density}"
  rm -f "${density_dir}/ic_brave_logo.png"
  if [[ -d "${density_dir}" && -f "${BRAVE_DIR}/android/BUILD.gn" ]]; then
    for f in "${density_dir}"/*; do
      [[ -f "${f}" ]] || continue
      fname="$(basename "${f}")"
      if ! grep -Fq "\"java/brave-res/drawable-${density}/${fname}\"" "${BRAVE_DIR}/android/BUILD.gn" 2>/dev/null; then
        rm -f "${f}"
      fi
    done
  fi
done

# 7. Clean up any stale brave_icon_search.xml in quick_search_engines drawables
QSE_DRAWABLE="${BRAVE_DIR}/browser/quick_search_engines/android/java/res/drawable"
if [[ -d "${QSE_DRAWABLE}" ]]; then
  rm -f "${QSE_DRAWABLE}/brave_icon_search.xml"
fi

# 8. Optional direct overlay to Chromium src directory
if [[ -n "${SRC_DIR}" && -d "${SRC_DIR}" ]]; then
  echo "Overlaying Cerium assets directly to Chromium src..."
  if [[ -d "${SRC_DIR}/chrome/app/theme/brave_origin/win" && -d "${STATIC_DIR}/app/theme/brave/win" ]]; then
    cp -f "${STATIC_DIR}/app/theme/brave/win/"*.ico "${SRC_DIR}/chrome/app/theme/brave_origin/win/" 2>/dev/null || true
  fi
  if [[ -d "${SRC_DIR}/components/omnibox/browser/vector_icons" && -f "${VECTOR_ICON_SRC}" ]]; then
    for o_icon in product.icon product_old.icon chrome_product.icon product_chrome_refresh.icon product_chrome_refresh_old.icon; do
      cp -f "${VECTOR_ICON_SRC}" "${SRC_DIR}/components/omnibox/browser/vector_icons/${o_icon}" 2>/dev/null || true
    done
  fi
  if [[ -d "${SRC_DIR}/ui/webui/resources/images" && -f "${cerium_svg}" ]]; then
    cp -f "${cerium_svg}" "${SRC_DIR}/ui/webui/resources/images/chrome_logo_dark.svg" 2>/dev/null || true
  fi
  if [[ -d "${SRC_DIR}/chrome/app/vector_icons" && -f "${VECTOR_ICON_MONO}" ]]; then
    cp -f "${VECTOR_ICON_MONO}" "${SRC_DIR}/chrome/app/vector_icons/browser_logo.icon" 2>/dev/null || true
    cp -f "${VECTOR_ICON_MONO}" "${SRC_DIR}/chrome/app/vector_icons/browser_logo_old.icon" 2>/dev/null || true
  fi
  echo " [OK] Overlaid Cerium assets directly to Chromium src."
fi

echo " [OK] Cerium vector and raster assets applied cleanly to brave-core."
