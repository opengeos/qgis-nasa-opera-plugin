# NASA OPERA QGIS Plugin

[![QGIS](https://img.shields.io/badge/QGIS-3.28+-green.svg)](https://qgis.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A QGIS plugin for searching, visualizing, and analyzing NASA OPERA (Observational Products for End-Users from Remote Sensing Analysis) satellite data products -- with an AI assistant for natural language interaction.

## About NASA OPERA

OPERA is a NASA project that provides analysis-ready data products derived from satellite observations. The project produces near-real-time and systematic global data products using optical and SAR satellite imagery.

Learn more: [NASA OPERA Project](https://www.jpl.nasa.gov/go/opera)

## Features

- **Search Interface**: Search NASA OPERA products by location, date range, and dataset type
- **Footprint Visualization**: Display search result footprints as vector layers on the map
- **Raster Display**: Visualize OPERA raster data directly in QGIS with cloud-optimized streaming
- **Virtual Mosaics**: Combine multiple granules into seamless mosaics via GDAL VRT
- **AI Assistant**: Use natural language to search, display, and analyze OPERA data (powered by LLMs)
- **Multiple LLM Providers**: OpenAI, Anthropic, Amazon Bedrock, Google Gemini, and local Ollama
- **Multiple Datasets**: Support for all OPERA products:
  - DSWX-HLS: Dynamic Surface Water Extent from Harmonized Landsat Sentinel-2
  - DSWX-S1: Dynamic Surface Water Extent from Sentinel-1
  - DIST-ALERT-HLS: Land Surface Disturbance Alert
  - DIST-ANN-HLS: Land Surface Disturbance Annual
  - RTC-S1: Radiometric Terrain Corrected SAR Backscatter
  - CSLC-S1: Coregistered Single-Look Complex
- **Settings Panel**: Configure Earthdata credentials, display options, and AI provider
- **Update Checker**: Check for plugin updates from GitHub

## Prerequisites

### NASA Earthdata Account

To access NASA OPERA data, you need a free NASA Earthdata account:

1. Go to [NASA Earthdata Registration](https://urs.earthdata.nasa.gov/users/new)
2. Create an account
3. Configure your credentials in the plugin settings

### Python Dependencies

The plugin manages dependencies automatically via an isolated virtual environment. On first use, open **Settings > Dependencies** and click **Install Dependencies** to install:

- `earthaccess` - NASA Earthdata search and download
- `geopandas` - Geospatial data manipulation
- `shapely` - Geometry operations
- `pandas` - Data analysis

For the AI Assistant, open **Settings > AI Assistant** and click **Install AI Dependencies** to install:

- `litellm` - Unified LLM interface for multiple providers

## Installation

### Method 1: Install from Source

1. Clone or download this repository:
   ```bash
   git clone https://github.com/opengeos/qgis-nasa-opera-plugin.git
   cd qgis-nasa-opera-plugin
   ```

2. Run the installation script:

   **Linux/macOS:**
   ```bash
   ./install.sh
   ```

   **Windows/Cross-platform (Python):**
   ```bash
   python install.py
   ```

3. Restart QGIS

4. Enable the plugin:
   - Go to **Plugins > Manage and Install Plugins...**
   - Search for "NASA OPERA"
   - Check the box to enable it

### Method 2: Manual Installation

1. Download or clone this repository

2. Copy the `nasa_opera` folder to your QGIS plugins directory:
   - **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - **macOS**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
   - **Windows**: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`

3. Restart QGIS and enable the plugin

## Usage

### Basic Workflow

1. **Open the Plugin**: Click the NASA OPERA icon in the toolbar or go to **NASA OPERA > NASA OPERA Search**

2. **Select Dataset**: Choose the OPERA product you want to search for

3. **Set Search Parameters**:
   - **Bounding Box**: Enter coordinates manually or click "Use Map Extent"
   - **Date Range**: Select start and end dates
   - **Max Results**: Set the maximum number of results

4. **Search**: Click the "Search" button to find available data

5. **View Results**:
   - **Show Footprints**: Display the spatial coverage of search results
   - **Display Single**: Load a specific granule's raster data
   - **Display Mosaic**: Create a virtual mosaic from selected granules

### AI Assistant

The AI Assistant lets you interact with NASA OPERA data using natural language.

1. **Setup**: Go to **NASA OPERA > Settings > AI Assistant** tab
   - Install AI dependencies (litellm)
   - Select your LLM provider (OpenAI, Anthropic, Bedrock, Gemini, or Ollama)
   - Enter your API key (not required for Ollama)
   - Click "Test Connection" to verify

2. **Open**: Click the AI Assistant icon in the toolbar or go to **NASA OPERA > AI Assistant**

3. **Ask Questions**: Type natural language queries such as:
   - "What OPERA datasets are available?"
   - "Search for surface water data in my current map extent"
   - "Find land disturbance alerts in California from 2024"
   - "Show me the latest DSWX-HLS data for Las Vegas area"
   - "Create a mosaic of the first 5 results"
   - "What layers do I have loaded?"

The AI assistant can search data, display footprints, load rasters, create mosaics, and manage map layers -- all through conversation.

**Supported LLM Providers:**

| Provider | Default Model | API Key Required |
|----------|--------------|-----------------|
| OpenAI | gpt-5.5 | Yes |
| Anthropic | claude-sonnet-4-6 | Yes |
| Amazon Bedrock | claude-sonnet-4-20250514 | AWS credentials |
| Google Gemini | gemini-3.1-flash-lite-preview | Yes |
| Ollama | llama3.1 | No (local) |

### Settings

Access settings via **NASA OPERA > Settings**:

- **Dependencies**: Install and manage core Python packages
- **Credentials**: Configure your NASA Earthdata username and password
- **Display**: Customize footprint styles and default colormap
- **Advanced**: Set default search parameters and cache options
- **AI Assistant**: Configure LLM provider, model, API key, and parameters

### First-Time Authentication

When you first run a search, the plugin will authenticate with NASA Earthdata:

1. If you haven't configured credentials, earthaccess will prompt for login
2. Credentials are stored in `~/.netrc` for future use
3. You can also configure credentials in the Settings panel

## Development

### Project Structure

```
qgis-nasa-opera-plugin/
├── nasa_opera/                 # Plugin source code
│   ├── __init__.py            # Plugin entry point
│   ├── nasa_opera.py          # Main plugin class
│   ├── metadata.txt           # Plugin metadata
│   ├── deps_manager.py        # Dependency management (isolated venv)
│   ├── uv_manager.py          # uv package installer
│   ├── ai/                    # AI agent module
│   │   ├── __init__.py
│   │   ├── llm_client.py      # litellm wrapper (multi-provider)
│   │   ├── agent.py           # Agent loop orchestration
│   │   ├── tools.py           # Tool registry + 10 core tools
│   │   ├── workers.py         # QThread worker for async LLM calls
│   │   └── oauth.py           # OAuth PKCE flow
│   ├── dialogs/               # UI widgets
│   │   ├── opera_dock.py      # Main search interface
│   │   ├── ai_chat_dock.py    # AI chat interface
│   │   ├── settings_dock.py   # Settings panel
│   │   └── update_checker.py  # Update checker dialog
│   └── icons/                 # Plugin icons
├── install.py                 # Python installation script
├── install.sh                 # Bash installation script
├── package_plugin.py          # Python packaging script
├── package_plugin.sh          # Bash packaging script
├── README.md                  # This file
└── LICENSE                    # MIT License
```

### Packaging for Distribution

To create a distributable zip file:

```bash
python package_plugin.py
# or
./package_plugin.sh
```

This creates `nasa_opera-{version}.zip` ready for upload to the QGIS Plugin Repository.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [NASA OPERA Project](https://www.jpl.nasa.gov/go/opera) for providing the data products
- [earthaccess](https://github.com/nsidc/earthaccess) for NASA Earthdata access
- [litellm](https://github.com/BerriAI/litellm) for unified LLM provider access
- [leafmap](https://github.com/opengeos/leafmap) for inspiration on the GUI design
- The QGIS community for the excellent GIS platform

## Support

- **Bug Reports**: [GitHub Issues](https://github.com/opengeos/qgis-nasa-opera-plugin/issues)
- **Feature Requests**: [GitHub Issues](https://github.com/opengeos/qgis-nasa-opera-plugin/issues)
- **Documentation**: [GitHub Wiki](https://github.com/opengeos/qgis-nasa-opera-plugin/wiki)
