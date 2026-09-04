
# TheHerta4

<div align="center">


[![GitHub stars](https://img.shields.io/github/stars/StarBobis/TheHerta4?style=flat&logo=github&color=gold)](https://github.com/StarBobis/TheHerta4/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/StarBobis/TheHerta4?style=flat&logo=github&color=blue)](https://github.com/StarBobis/TheHerta4/forks)
[![GitHub issues](https://img.shields.io/github/issues/StarBobis/TheHerta4?style=flat&logo=github&color=red)](https://github.com/StarBobis/TheHerta4/issues)
[![GitHub license](https://img.shields.io/github/license/StarBobis/TheHerta4?style=flat&color=brightgreen)](https://github.com/StarBobis/TheHerta4/blob/main/LICENSE.txt)
[![GitHub last commit](https://img.shields.io/github/last-commit/StarBobis/TheHerta4?style=flat&logo=git&color=orange)](https://github.com/StarBobis/TheHerta4/commits/main)
[![GitHub Downloads (all assets, latest release)](https://img.shields.io/github/downloads/StarBobis/TheHerta4/latest/total?style=flat&logo=github&color=blue&label=最新版下载量)](https://github.com/StarBobis/TheHerta4/releases/latest)
[![Blender](https://img.shields.io/badge/Blender-5.2%20LTS-e67e22?style=flat&logo=blender&logoColor=white)](https://www.blender.org/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![GitHub release](https://img.shields.io/github/v/release/StarBobis/TheHerta4?style=flat-square&logo=github)](https://github.com/StarBobis/TheHerta4/releases)
[![VibeCoding With DeepSeek V4 Pro](https://img.shields.io/badge/VibeCoding_With-DeepSeek_V4_Pro-4D6BFE?style=flat&logo=deepseek&logoColor=white)](https://deepseek.com/)

</div>


📦 **A Blender addon for SSMT4** — Import and export SSMT4 model format directly in Blender. Built for 3Dmigoto-based game modding.

- 🔄 SSMT4 and TheHerta4 versions are almost always updated together. Please use the latest versions of both to avoid feature mismatches.
- 🐞 **Blender 5.2 LTS** is required. Older Blender versions are not supported.
- 📦 **Requirements:** `fake-bpy-module-5.2`, `numpy`

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🎮 **Multi-Game Support** | Import/export for 10+ popular games (see below) |
| 🧩 **Blueprint Node System** | Visual node-based mod editing in Blender |
| 📥 **SSMT4 Import** | Import models from SSMT4 workspace |
| 📤 **Mod Export** | Export edited models back to 3Dmigoto Mod format |
| 🔄 **Buffer & IB/VB Handling** | Full support for index/vertex buffer manipulation |
| 🎨 **Texture Override** | Per-game texture slot mapping and override |
| 🦴 **Shape Key Support** | Morph target / shape key editing |
| ⚡ **Batch Processing** | Generate mods from blueprint trees |
| 🔌 **Extensible** | Game-specific exporters via `LogicName` system |

---

## 🎮 Supported Games

### ✅ Fully Supported (Active Maintenance)

| Game | ID | Engine |
|------|----|--------|
| 🏔️ **Genshin Impact** | `GIMI` | Unity |
| ⚡ **Honkai Impact 3rd** | `HIMI` | Unity |
| 🌌 **Honkai: Star Rail** | `SRMI` | Unity |
| 🌃 **Zenless Zone Zero** | `ZZMI` | Unity |
| 🌃 **Zenless Zone Zero DX12** | `ZZMIDX12` | Unity |
| 🌊 **Wuthering Waves** | `WWMI` | Unreal |
| �️ **Arknights: Endfield** (明日方舟终末地) | `EFMI` | Unity |

### ⚠️ Community / Occasional Maintenance

| Game | ID | Notes |
|------|----|-------|
| 🎭 **Identity V** | `IdentityV` | NeoX engine, limited maintenance |
| ❄️ **Snowbreak: Containment Zone** | `SnowBreak` | Fallback option (native mod support available) |
| 🏮 **Where Winds Meet** | `YYSLS` | Limited player base |
| 🌐 **Neverness to Everness** | `NTEMI` | Beta testing phase |
| 🔫 **Girls' Frontline 2** | `GF2` | CPU-PreSkinning approach |

### 🔮 Reserved (In Testing / Upcoming)

| Game | ID |
|------|----|
| 💙 **Azur Promilia** (蓝色星原) | `APMI` |
---

## 🚀 Quick Start

### Installation

1. 💾 [Download the latest release](https://github.com/StarBobis/TheHerta4/releases/latest)
2. 🌀 Open Blender → `Edit` → `Preferences` → `Add-ons`
3. 📂 Click **Install...** and select the downloaded `.zip`
4. ✅ Enable **"TheHerta4"** from the add-ons list
5. 🔍 Find the panel in `3D Viewport` → `Sidebar (N)` → **TheHerta4** and **Sword4** tab

### Basic Workflow

```
1️⃣ Configure → Set your SSMT4 workspace path in the panel
2️⃣ Select Game → Choose your game preset (GIMI, SRMI, etc.)
3️⃣ Import → Load models from the workspace
4️⃣ Edit → Modify meshes, weights, shape keys in Blender
5️⃣ Export → Generate the mod files (buffers + ini) via blueprint tree
```

---

## 💖 Support Development

If you find this tool useful, consider supporting the project:

<a href="https://afdian.com/a/NicoMico666"><img width="200" src="https://pic1.afdiancdn.com/static/img/welcome/button-sponsorme.png" alt=""></a>

---

## 🔧 Blueprint Nodes & Forks

This repository (**TheHerta4**) focuses on the **core import/export engine**. Complex blueprint nodes are developed separately in fork versions.

👉 For the full feature set, check out the versions maintained by **XiEr**:
- [TheHerta3 by xuhuan9102](https://github.com/xuhuan9102/TheHerta3)
- [TheHerta4 by xuhuan9102](https://github.com/xuhuan9102/TheHerta4)

> If you need large-scale feature extensions, please **fork** this repo and develop in your own repository. The main repo is dedicated to core architecture — additional extensions (blueprint nodes, etc.) are maintained by fork authors.

📝 **Have your own branch?** Submit a PR to add it to this list!

### For Developers

To work on the plugin itself:
- Use **VSCode** with the [**Blender Development**](https://github.com/JacquesLucke/blender_vscode) extension (by Jacques Lucke)
- See [`README_DEV.md`](README_DEV.md) for detailed development notes

---



## ⭐ Star History

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=StarBobis/TheHerta4&type=Date)](https://star-history.com/#StarBobis/TheHerta4&Date)

</div>

---

## 🙏 Special Thanks

TheHerta4 learns from several different projects. Without their wonderful code, TheHerta4 wouldn't be this amazing.

Great thanks to:

- [DarkStarSword / 3D-Fixes](https://github.com/DarkStarSword/3d-fixes)
- [SilentNightSound / GI-Model-Importer](https://github.com/SilentNightSound/GI-Model-Importer)
- [leotorrez / XXMITools](https://github.com/leotorrez/XXMITools)
- [leotorrez / LeoTools](https://github.com/leotorrez/LeoTools)
- [leotorrez / ZZ-Model-Importer](https://github.com/leotorrez/ZZ-Model-Importer)
- [SpectrumQT / WWMI-Tools](https://github.com/SpectrumQT/WWMI-Tools)
- [SpectrumQT / EFMI-Tools](https://github.com/SpectrumQT/EFMI-Tools)
- [ssice-a / mod_importer](https://github.com/ssice-a/mod_importer)
- [Grim-es / material-combiner-addon](https://github.com/Grim-es/material-combiner-addon)


