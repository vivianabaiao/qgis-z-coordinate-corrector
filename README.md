# QGIS Z-Coordinate Corrector

A QGIS plugin that detects and fixes elevation inconsistencies in 3D line data.

> **Note**: I built this tool to solve a recurring problem at my job. I'm sharing it publicly in case it helps others facing similar issues with elevation data.

## What It Does

When you have line shapefiles with Z-coordinates (elevation), this plugin:

1. **Finds problems** - Detects where the same point has different elevations
2. **Fixes them** - Corrects inconsistencies using the minimum elevation
3. **Validates** - Optionally checks alignment with contour lines
4. **Exports** - Saves clean, corrected shapefiles

## Who Needs This

- Surveyors cleaning up topographic data
- Engineers working with utility networks (water, sewer, gas)
- GIS professionals integrating data from multiple sources
- Anyone with 3D line data that has elevation errors

## The Problem It Solves

### Example Problem:
```
You have survey lines where intersections don't match:

Line A at point (100, 200): elevation = 45.8m
Line B at point (100, 200): elevation = 45.2m
Line C at point (100, 200): elevation = 46.1m

Same location, three different elevations → ERROR
```

### The Solution:
```
After correction:

Line A at point (100, 200): elevation = 45.2m
Line B at point (100, 200): elevation = 45.2m  
Line C at point (100, 200): elevation = 45.2m

Same location, same elevation → FIXED
```

## How It Works

### The Rule
**At any point, all lines use the MINIMUM elevation**

Why minimum? It's the conservative approach - better to underestimate elevation than overestimate it (especially for infrastructure planning).

### The Process

**Tab 1 - Input**: Select your layers and output folder

**Tab 2 - Detect**: Find all the problems
- Checks every intersection point
- Finds where elevations don't match
- Shows you statistics (how many problems, how big the differences)

**Tab 3 - Correct**: Fix the problems
- **Internal corrections**: Fix issues within each layer
- **External corrections**: Fix issues between different layers

**Tab 4 - Contour** (Optional): Align with reference contours
- If you have contour lines with known elevations
- Ensures your data matches the contours
- Can convert DXF contour files to shapefiles

**Tab 5 - Verify**: Make sure everything is fixed
- Must show **0 differences** to pass
- If problems remain, go back and correct again

**Tab 6 - Export**: Save the corrected data
- Exports shapefiles with fixed elevations
- Creates detailed reports of all changes
- Optionally loads corrected layers into QGIS

## Installation

1. Download `z_coordinate_corrector_enhanced.py`, `__init__.py` and `metadata.txt`

2. Copy to your QGIS plugins folder:
   - **Windows**: `C:\Users\YourName\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\z_corrector_enhanced\`
   - **Mac**: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/z_corrector_enhanced/`
   - **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/z_corrector_enhanced/`

3. Restart QGIS

4. Enable: `Plugins` → `Manage and Install Plugins` → Check `Z Corrector Enhanced`

## Requirements

- QGIS 3.40.10 or newer
- Line shapefiles with Z-coordinates (3D geometries)

## Quick Example

**Scenario**: You have 3 utility shapefiles (water, sewer, roads) that intersect but have different elevations at crossings.

**Solution**:
```
1. Load all 3 layers in QGIS
2. Open plugin → Tab 1: Select all 3 layers, choose output folder
3. Tab 2: Click "Detect Internal Issues" → Finds 234 problems
4. Tab 3: Click "Apply Internal Corrections" → Fixes 112 problems
5. Tab 3: Click "Apply External Corrections" → Fixes 122 problems  
6. Tab 5: Click "Run Verification" → 0 differences ✓
7. Tab 6: Click "Export" → Done!
```

## Features

### Core Features
- Detect elevation inconsistencies automatically
- Fix issues within layers (internal)
- Fix issues between layers (external)
- Validate against contour lines
- Quality verification (ensures 0 errors)
- Export corrected shapefiles

### Nice-to-Have Features
- Undo system (revert corrections)
- Progress bars with time estimates
- Detailed CSV logs of all changes
- Summary reports
- DXF to shapefile converter
- Auto-load exported layers to map


## Output Files

After export, you get:

1. **Corrected Shapefiles**: `LayerName_CORRECTED_20240216_143022.shp`
   - Fixed elevations
   - All original attributes preserved

2. **Correction Log**: `CORRECTIONS_20240216_143022.csv`
   - Lists every change made
   - Shows before/after elevations

3. **Summary Report**: `EXPORT_SUMMARY_20240216_143022.txt`
   - Statistics
   - Processing details
   - List of generated files

---

**Originally created for personal use in surveying/GIS work. Sharing it in case others find it useful.**
