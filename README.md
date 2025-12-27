# NASA OPERA QGIS Plugin

[![QGIS](https://img.shields.io/badge/QGIS-3.28+-green.svg)](https://qgis.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A QGIS plugin for searching and visualizing NASA OPERA (Observational Products for End-Users from Remote Sensing Analysis) satellite data products.

![NASA OPERA Plugin](https://www.jpl.nasa.gov/images/opera-logo-color.png)

## About NASA OPERA

OPERA is a NASA project that provides analysis-ready data products derived from satellite observations. The project produces near-real-time and systematic global data products using optical and SAR satellite imagery.

Learn more: [NASA OPERA Project](https://www.jpl.nasa.gov/go/opera)

## Features

- **Search Interface**: Search NASA OPERA products by location, date range, and dataset type
- **Footprint Visualization**: Display search result footprints as vector layers on the map
- **Raster Display**: Visualize OPERA raster data directly in QGIS
- **Multiple Datasets**: Support for all OPERA products:
  - DSWX-HLS: Dynamic Surface Water Extent from Harmonized Landsat Sentinel-2
  - DSWX-S1: Dynamic Surface Water Extent from Sentinel-1
  - DIST-ALERT-HLS: Land Surface Disturbance Alert
  - DIST-ANN-HLS: Land Surface Disturbance Annual
  - RTC-S1: Radiometric Terrain Corrected SAR Backscatter
  - CSLC-S1: Coregistered Single-Look Complex
- **Settings Panel**: Configure Earthdata credentials and display options
- **Update Checker**: Check for plugin updates from GitHub

## Prerequisites

### NASA Earthdata Account

To access NASA OPERA data, you need a free NASA Earthdata account:

1. Go to [NASA Earthdata Registration](https://urs.earthdata.nasa.gov/users/new)
2. Create an account
3. Configure your credentials in the plugin settings

### Python Dependencies

The plugin requires the following Python packages:

```bash
pip install earthaccess geopandas shapely pandas
```

Or if using conda:

```bash
conda install -c conda-forge earthaccess geopandas shapely pandas
```

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
   - Go to **Plugins → Manage and Install Plugins...**
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

1. **Open the Plugin**: Click the NASA OPERA icon in the toolbar or go to **NASA OPERA → NASA OPERA Search**

2. **Select Dataset**: Choose the OPERA product you want to search for

3. **Set Search Parameters**:
   - **Bounding Box**: Enter coordinates manually or click "Use Map Extent"
   - **Date Range**: Select start and end dates
   - **Max Results**: Set the maximum number of results

4. **Search**: Click the "Search" button to find available data

5. **View Results**:
   - **Show Footprints**: Display the spatial coverage of search results
   - **Display Single**: Load a specific granule's raster data

### Settings

Access settings via **NASA OPERA → Settings**:

- **Credentials**: Configure your NASA Earthdata username and password
- **Display**: Customize footprint styles and default colormap
- **Advanced**: Set default search parameters and cache options

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
│   ├── dialogs/               # Dialog widgets
│   │   ├── opera_dock.py      # Main search interface
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

### Testing

To test the plugin in QGIS with a specific conda environment:

```bash
# Activate your environment
conda activate geo

# Install the plugin
python install.py

# Start QGIS
qgis
```

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
- [leafmap](https://github.com/opengeos/leafmap) for inspiration on the GUI design
- The QGIS community for the excellent GIS platform

## Support

- **Bug Reports**: [GitHub Issues](https://github.com/opengeos/qgis-nasa-opera-plugin/issues)
- **Feature Requests**: [GitHub Issues](https://github.com/opengeos/qgis-nasa-opera-plugin/issues)
- **Documentation**: [GitHub Wiki](https://github.com/opengeos/qgis-nasa-opera-plugin/wiki)

## Changelog

### 0.1.0 (Initial Release)

- NASA OPERA data search interface
- Support for all OPERA products (DSWX-HLS, DSWX-S1, DIST-ALERT, DIST-ANN, RTC-S1, CSLC-S1)
- Footprint visualization
- Raster layer display
- Settings panel with Earthdata credentials
- Update checker
