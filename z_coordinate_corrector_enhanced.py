"""
QGIS Z-Coordinate Corrector - ENHANCED VERSION
Compatible with QGIS 3.40.10

Complete Z-coordinate correction tool with:
- Quality verification (0 differences check)
- Iterative corrections workflow
- Intersection detection and vertex insertion
- Progress indicators with time estimates
- Comprehensive reporting and logging
- Color-coded UI feedback
"""

from qgis.PyQt.QtWidgets import *
from qgis.PyQt.QtCore import Qt, QTimer, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsProjectionSelectionWidget
from qgis.core import *
import os
import csv
import re
import math
import time
from datetime import datetime
from collections import defaultdict


def classFactory(iface):
    return ZCoordinatePlugin(iface)


class ZCoordinatePlugin(QDialog):
    def __init__(self, iface):
        super().__init__()
        self.iface = iface
        self.setWindowTitle("Z-Coordinate Corrector - Enhanced")
        self.resize(950, 750)
        
        # Storage
        self.paths = {'dxf': '', 'output': '', 'contour': ''}
        self.nodes_csv = []
        self.correction_history = []
        self.detection_stats = {}
        self.detected_contour_issues = []  # Store detected contour mismatches
        
        # Undo system
        self.undo_stack = []  # Stack of correction states
        self.max_undo_levels = 10  # Keep last 10 corrections
        
        # Layer duplication tracking
        self.duplicated_layers = {}  # {original_layer_id: duplicated_layer_id}
        
        # Menu action
        self.action = QAction("Z Corrector Enhanced", iface.mainWindow())
        self.action.triggered.connect(self.show)
        iface.addPluginToMenu("Z Tools", self.action)
        iface.addToolBarIcon(self.action)
        
        self.build_ui()
    
    def initGui(self):
        """QGIS requires this method"""
        pass
    
    def build_ui(self):
        """Build the entire UI"""
        main_layout = QVBoxLayout()
        
        # Tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self.tab_input(), "1. Input")
        self.tabs.addTab(self.tab_detect(), "2. Detect")
        self.tabs.addTab(self.tab_correct(), "3. Correct")
        self.tabs.addTab(self.tab_contour(), "4. Contour Lines(Optional)")
        self.tabs.addTab(self.tab_verify(), "5. Verify")
        self.tabs.addTab(self.tab_export(), "6. Export")
        main_layout.addWidget(self.tabs)
        
        # Progress bar with label
        progress_widget = QWidget()
        progress_layout = QVBoxLayout()
        self.progress_label = QLabel("")
        self.progress_label.setVisible(False)
        progress_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)
        progress_widget.setLayout(progress_layout)
        main_layout.addWidget(progress_widget)
        
        # Status bar with color coding
        self.status = QLabel("Ready - Select input files to begin")
        self.update_status("Ready - Select input files to begin", "info")
        main_layout.addWidget(self.status)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        main_layout.addWidget(close_btn)
        
        self.setLayout(main_layout)
        
        # Load layers now that all UI elements are created
        self.load_layers()
    
    def update_status(self, text, status_type="info"):
        """Update status bar with color coding"""
        self.status.setText(text)
        colors = {
            "info": "background:#e3f2fd;color:#1976d2",
            "success": "background:#e8f5e9;color:#2e7d32;font-weight:bold",
            "warning": "background:#fff3e0;color:#e65100;font-weight:bold",
            "error": "background:#ffebee;color:#c62828;font-weight:bold",
            "processing": "background:#f3e5f5;color:#6a1b9a"
        }
        self.status.setStyleSheet(f"padding:8px;border:2px solid #ccc;border-radius:4px;{colors.get(status_type, colors['info'])}")
    
    def show_progress(self, visible=True, text="", value=0, maximum=100):
        """Show/hide progress bar with text"""
        self.progress_bar.setVisible(visible)
        self.progress_label.setVisible(visible and bool(text))
        if text:
            self.progress_label.setText(text)
        if visible:
            self.progress_bar.setMaximum(maximum)
            self.progress_bar.setValue(value)
    
    def tab_input(self):
        """Input tab with validation"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # === OPTION SELECTOR ===
        option_selector = QGroupBox("Select Input Method")
        option_layout = QVBoxLayout()
        
        self.input_option_group = QButtonGroup()
        
        self.option_dxf = QRadioButton("Option A: Import from DXF file")
        self.option_dxf.setChecked(True)
        self.input_option_group.addButton(self.option_dxf)
        option_layout.addWidget(self.option_dxf)
        
        self.option_layers = QRadioButton("Option B: Use existing layer(s)")
        self.input_option_group.addButton(self.option_layers)
        option_layout.addWidget(self.option_layers)
        
        option_selector.setLayout(option_layout)
        layout.addWidget(option_selector)
        
        # Connect toggle to show/hide sections
        self.option_dxf.toggled.connect(self.toggle_input_options)
        
        # DXF Option (Option A)
        self.grp_dxf = QGroupBox("Option A: Import DXF")
        lay1 = QVBoxLayout()
        
        btn1 = QPushButton("Select DXF File")
        btn1.setMinimumHeight(40)
        btn1.clicked.connect(self.select_dxf)
        lay1.addWidget(btn1)
        
        self.dxf_display = QTextEdit()
        self.dxf_display.setMaximumHeight(60)
        self.dxf_display.setReadOnly(True)
        self.dxf_display.setPlainText("No DXF selected")
        self.dxf_display.setStyleSheet("background:#f5f5f5;border:1px dashed #999")
        lay1.addWidget(self.dxf_display)
        
        self.convert_btn = QPushButton("Convert DXF to Shapefile")
        self.convert_btn.setMinimumHeight(40)
        self.convert_btn.clicked.connect(self.do_convert)
        self.convert_btn.setEnabled(False)
        self.convert_btn.setStyleSheet("background:#e0e0e0")
        lay1.addWidget(self.convert_btn)
        
        self.grp_dxf.setLayout(lay1)
        layout.addWidget(self.grp_dxf)
        
        # Shapefile Option (Option B) - NOW SUPPORTS MULTIPLE LAYERS
        self.grp_layers = QGroupBox("Option B: Select Layer(s) to Check")
        lay2 = QVBoxLayout()
        
        # Info text
        info = QLabel(
            "Select one or more layers to check Z-coordinates:\n"
            "• Single layer: Check nodes within that layer\n"
            "• Multiple layers: Check nodes across all selected layers"
        )
        info.setWordWrap(True)
        info.setStyleSheet("background:#e3f2fd;padding:8px;border-radius:4px;font-size:11px")
        lay2.addWidget(info)
        
        # List widget for multiple selection
        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(QAbstractItemView.MultiSelection)
        self.layer_list.setMinimumHeight(120)
        self.layer_list.itemSelectionChanged.connect(self.validate_inputs)
        lay2.addWidget(self.layer_list)
        
        # Buttons row
        btn_row = QHBoxLayout()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setMinimumHeight(35)
        refresh_btn.clicked.connect(self.load_layers)
        refresh_btn.setToolTip("Refresh the list of available layers")
        btn_row.addWidget(refresh_btn)
        
        select_all_btn = QPushButton("Select All")
        select_all_btn.setMinimumHeight(35)
        select_all_btn.clicked.connect(self.select_all_layers)
        btn_row.addWidget(select_all_btn)
        
        clear_btn = QPushButton("Clear")
        clear_btn.setMinimumHeight(35)
        clear_btn.clicked.connect(self.clear_layer_selection)
        btn_row.addWidget(clear_btn)
        
        lay2.addLayout(btn_row)
        
        # Duplicate layers button
        duplicate_layout = QHBoxLayout()
        self.duplicate_layers_btn = QPushButton("Create Working Copies (Recommended)")
        self.duplicate_layers_btn.setMinimumHeight(40)
        self.duplicate_layers_btn.setStyleSheet("background:#fff3e0;font-weight:bold")
        self.duplicate_layers_btn.clicked.connect(self.duplicate_selected_layers)
        self.duplicate_layers_btn.setEnabled(False)
        self.duplicate_layers_btn.setToolTip("Creates duplicates of selected layers to work on safely.\nOriginal layers remain untouched.")
        duplicate_layout.addWidget(self.duplicate_layers_btn)
        lay2.addLayout(duplicate_layout)
        
        # Selection summary
        self.layer_summary = QLabel("No layers selected")
        self.layer_summary.setStyleSheet("padding:5px;background:#f5f5f5;border:1px solid #ccc;border-radius:3px;font-size:11px")
        lay2.addWidget(self.layer_summary)
        
        self.grp_layers.setLayout(lay2)
        layout.addWidget(self.grp_layers)
        
        # Initially hide Option B
        self.grp_layers.setVisible(False)
        
        # Output Folder (Required)
        grp3 = QGroupBox("Output Folder (Required)")
        lay3 = QVBoxLayout()
        
        btn3 = QPushButton("Select Output Folder")
        btn3.setMinimumHeight(40)
        btn3.clicked.connect(self.select_output)
        lay3.addWidget(btn3)
        
        self.output_display = QTextEdit()
        self.output_display.setMaximumHeight(60)
        self.output_display.setReadOnly(True)
        self.output_display.setPlainText("No folder selected")
        self.output_display.setStyleSheet("background:#f5f5f5;border:1px dashed #999")
        lay3.addWidget(self.output_display)
        
        grp3.setLayout(lay3)
        layout.addWidget(grp3)
        
        layout.addStretch()
        widget.setLayout(layout)
        
        # Don't call load_layers here - will be called after all tabs are created
        
        return widget
    
    def tab_detect(self):
        """Detection tab with intersection detection"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        info = QLabel(
            "Detects nodes where Z values differ:\n"
            "• Vertex nodes (same XY, different Z)\n"
            "• Intersection nodes (line crossings)\n"
            "• Creates comprehensive node inventory"
        )
        info.setWordWrap(True)
        info.setStyleSheet("background:#e3f2fd;padding:10px;border-radius:4px")
        layout.addWidget(info)
        
        # Detection options
        options_grp = QGroupBox("Detection Options")
        options_layout = QVBoxLayout()
        
        self.detect_intersections_cb = QCheckBox("Detect and insert vertices at intersections")
        self.detect_intersections_cb.setChecked(True)
        self.detect_intersections_cb.setToolTip("Find line crossings and insert vertices for better analysis")
        options_layout.addWidget(self.detect_intersections_cb)
        
        self.intersection_tolerance = QDoubleSpinBox()
        self.intersection_tolerance.setPrefix("Tolerance: ")
        self.intersection_tolerance.setSuffix(" units")
        self.intersection_tolerance.setDecimals(6)
        self.intersection_tolerance.setValue(0.001)
        self.intersection_tolerance.setToolTip("Distance tolerance for intersection detection")
        options_layout.addWidget(self.intersection_tolerance)
        
        options_grp.setLayout(options_layout)
        layout.addWidget(options_grp)
        
        # Detect button
        self.detect_btn = QPushButton("RUN DETECTION")
        self.detect_btn.setMinimumHeight(50)
        self.detect_btn.setStyleSheet("font-weight:bold;font-size:14px")
        self.detect_btn.clicked.connect(self.run_detection)
        self.detect_btn.setEnabled(False)
        layout.addWidget(self.detect_btn)
        
        # Statistics display
        self.detect_stats_display = QTextEdit()
        self.detect_stats_display.setReadOnly(True)
        self.detect_stats_display.setMaximumHeight(120)
        self.detect_stats_display.setStyleSheet("background:#f5f5f5;font-family:monospace")
        layout.addWidget(self.detect_stats_display)
        
        # Export problem nodes button
        self.export_nodes_btn = QPushButton("Export Problem Nodes as Point Shapefile")
        self.export_nodes_btn.setMinimumHeight(45)
        self.export_nodes_btn.setStyleSheet("background:#e1f5fe;font-weight:bold")
        self.export_nodes_btn.clicked.connect(self.export_problem_nodes)
        self.export_nodes_btn.setEnabled(False)
        self.export_nodes_btn.setToolTip(
            "Creates a point shapefile with all detected problem nodes.\n"
            "Each point includes: coordinates, Z values, layer info.\n"
            "Use this to visualize problems on the map before correction."
        )
        layout.addWidget(self.export_nodes_btn)
        
        # Results
        self.detect_results = QTextEdit()
        self.detect_results.setReadOnly(True)
        self.detect_results.setStyleSheet("font-family:monospace")
        layout.addWidget(self.detect_results)
        
        widget.setLayout(layout)
        return widget
    
    def tab_correct(self):
        """Correction tab with iterative workflow"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        info = QLabel(
            "Correction Types:\n"
            "• Internal: Corrects SINGLE selected layer (Z = MIN within that layer)\n"
            "• Cross-Layer: Corrects MULTIPLE layers together (Z = MIN across all layers)\n"
            "• Contour: Aligns with contour elevations (requires contour file)"
        )
        info.setWordWrap(True)
        info.setStyleSheet("background:#fff3e0;padding:10px;border-radius:4px")
        layout.addWidget(info)
        
        # === THREE CORRECTION TYPES ===
        
        # 1. INTERNAL NODES CORRECTION (always available)
        self.internal_group = QGroupBox("1. Internal Nodes Correction")
        internal_layout = QVBoxLayout()
        internal_info = QLabel("Fixes Z differences WITHIN each shapefile\nRule: Z = MINIMUM at each node")
        internal_info.setStyleSheet("color:#666;font-style:italic;padding:5px")
        internal_layout.addWidget(internal_info)
        
        self.correct_internal_btn = QPushButton("Apply Internal Corrections")
        self.correct_internal_btn.setMinimumHeight(45)
        self.correct_internal_btn.clicked.connect(self.apply_internal)
        self.correct_internal_btn.setEnabled(False)
        self.correct_internal_btn.setToolTip("Corrects Z differences within each shapefile - Z = MINIMUM")
        internal_layout.addWidget(self.correct_internal_btn)
        self.internal_group.setLayout(internal_layout)
        layout.addWidget(self.internal_group)
        
        # 2. EXTERNAL NODES CORRECTION (only if multiple layers)
        self.external_group = QGroupBox("2. External Nodes Correction")
        external_layout = QVBoxLayout()
        external_info = QLabel("Fixes Z differences BETWEEN different shapefiles\nRule: Z = MINIMUM across all layers")
        external_info.setStyleSheet("color:#666;font-style:italic;padding:5px")
        external_layout.addWidget(external_info)
        
        self.correct_external_btn = QPushButton("Apply External Corrections")
        self.correct_external_btn.setMinimumHeight(45)
        self.correct_external_btn.clicked.connect(self.apply_external)
        self.correct_external_btn.setEnabled(False)
        self.correct_external_btn.setToolTip("Corrects Z differences between shapefiles - MINIMUM Z from all layers prevails")
        external_layout.addWidget(self.correct_external_btn)
        self.external_group.setLayout(external_layout)
        layout.addWidget(self.external_group)
        
        # === VERIFICATION ===
        
        # Undo button
        undo_group = QGroupBox("Undo System")
        undo_layout = QVBoxLayout()
        
        self.undo_btn = QPushButton("Undo Last Correction")
        self.undo_btn.setMinimumHeight(40)
        self.undo_btn.setStyleSheet("background:#ffebee")
        self.undo_btn.clicked.connect(self.undo_last_correction)
        self.undo_btn.setEnabled(False)
        self.undo_btn.setToolTip("Revert the most recent correction")
        undo_layout.addWidget(self.undo_btn)
        
        self.undo_status = QLabel("No corrections to undo")
        self.undo_status.setStyleSheet("color:#666;font-size:10px;padding:5px")
        undo_layout.addWidget(self.undo_status)
        
        undo_group.setLayout(undo_layout)
        layout.addWidget(undo_group)
        
        # Quick verify button
        self.quick_verify_btn = QPushButton("Quick Verify (Check if corrections worked)")
        self.quick_verify_btn.setMinimumHeight(40)
        self.quick_verify_btn.clicked.connect(self.quick_verify)
        self.quick_verify_btn.setEnabled(False)
        layout.addWidget(self.quick_verify_btn)
        
        # Correct remaining button
        self.correct_remaining_btn = QPushButton("Correct Remaining Issues")
        self.correct_remaining_btn.setMinimumHeight(40)
        self.correct_remaining_btn.clicked.connect(self.correct_remaining)
        self.correct_remaining_btn.setVisible(False)
        layout.addWidget(self.correct_remaining_btn)
        
        # Correction summary
        self.correction_summary = QTextEdit()
        self.correction_summary.setReadOnly(True)
        self.correction_summary.setMaximumHeight(100)
        self.correction_summary.setStyleSheet("background:#f5f5f5;font-family:monospace")
        layout.addWidget(self.correction_summary)
        
        # Results
        self.correct_results = QTextEdit()
        self.correct_results.setReadOnly(True)
        self.correct_results.setStyleSheet("font-family:monospace")
        layout.addWidget(self.correct_results)
        
        widget.setLayout(layout)
        return widget
    
    def tab_contour(self):
        """Contour Lines Processing tab (OPTIONAL)"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Header info
        header = QLabel(
            "⚙ CONTOUR PROCESSING (OPTIONAL)\n\n"
            "Use this tab ONLY if you have contour reference lines.\n"
            "This step aligns your corrected data with reference contour elevations."
        )
        header.setWordWrap(True)
        header.setStyleSheet("font-weight:bold;background:#fff3e0;padding:10px;border-radius:4px")
        layout.addWidget(header)
        
        # STEP 1: CONVERT DXF (if needed)
        convert_group = QGroupBox("Step 1: Convert DXF to Shapefile (if needed)")
        convert_layout = QVBoxLayout()
        
        convert_info = QLabel(
            "If your contour lines are in DXF format, convert them first.\n"
            "Skip this step if you already have a shapefile."
        )
        convert_info.setStyleSheet("color:#666;font-style:italic;padding:5px")
        convert_layout.addWidget(convert_info)
        
        btn_convert_dxf = QPushButton("Convert DXF to Shapefile")
        btn_convert_dxf.setMinimumHeight(45)
        btn_convert_dxf.setStyleSheet("background:#e3f2fd")
        btn_convert_dxf.clicked.connect(self.convert_dxf_to_shapefile)
        btn_convert_dxf.setToolTip("Convert a DXF contour file to Shapefile format")
        convert_layout.addWidget(btn_convert_dxf)
        
        convert_group.setLayout(convert_layout)
        layout.addWidget(convert_group)
        
        # STEP 2: SELECT CONTOUR FILE
        select_group = QGroupBox("Step 2: Select Contour Shapefile")
        select_layout = QVBoxLayout()
        
        select_info = QLabel("Select your contour reference shapefile (must contain line geometries with Z values)")
        select_info.setStyleSheet("color:#666;font-style:italic;padding:5px")
        select_layout.addWidget(select_info)
        
        btn_contour = QPushButton("Select Contour Shapefile")
        btn_contour.setMinimumHeight(45)
        btn_contour.clicked.connect(self.select_contour)
        select_layout.addWidget(btn_contour)
        
        self.contour_display = QTextEdit()
        self.contour_display.setMaximumHeight(60)
        self.contour_display.setReadOnly(True)
        self.contour_display.setPlainText("No contour file selected")
        self.contour_display.setStyleSheet("background:#f5f5f5;border:1px dashed #999")
        select_layout.addWidget(self.contour_display)
        
        select_group.setLayout(select_layout)
        layout.addWidget(select_group)
        
        # STEP 3: DETECT CONTOUR MISMATCHES
        detect_contour_group = QGroupBox("Step 3: Detect Contour Mismatches")
        detect_contour_layout = QVBoxLayout()
        
        detect_contour_info = QLabel("Find intersections where your data doesn't match contour elevations")
        detect_contour_info.setStyleSheet("color:#666;font-style:italic;padding:5px")
        detect_contour_layout.addWidget(detect_contour_info)
        
        self.detect_contour_btn = QPushButton("Detect Contour Mismatches")
        self.detect_contour_btn.setMinimumHeight(45)
        self.detect_contour_btn.clicked.connect(self.detect_contour_issues)
        self.detect_contour_btn.setEnabled(False)
        self.detect_contour_btn.setToolTip("Find nodes that intersect contour lines with different Z values")
        detect_contour_layout.addWidget(self.detect_contour_btn)
        
        detect_contour_group.setLayout(detect_contour_layout)
        layout.addWidget(detect_contour_group)
        
        # STEP 4: APPLY CONTOUR CORRECTIONS
        correct_contour_group = QGroupBox("Step 4: Apply Contour Corrections")
        correct_contour_layout = QVBoxLayout()
        
        correct_contour_info = QLabel(
            "Aligns nodes with reference contour lines\n"
            "Rule: Z = CONTOUR VALUE at intersections"
        )
        correct_contour_info.setStyleSheet("color:#666;font-style:italic;padding:5px")
        correct_contour_layout.addWidget(correct_contour_info)
        
        self.correct_contour_btn = QPushButton("Apply Contour Corrections")
        self.correct_contour_btn.setMinimumHeight(45)
        self.correct_contour_btn.clicked.connect(self.apply_contour)
        self.correct_contour_btn.setEnabled(False)
        self.correct_contour_btn.setToolTip("Aligns Z values with contour reference lines")
        correct_contour_layout.addWidget(self.correct_contour_btn)
        
        correct_contour_group.setLayout(correct_contour_layout)
        layout.addWidget(correct_contour_group)
        
        # Results
        self.contour_results = QTextEdit()
        self.contour_results.setReadOnly(True)
        self.contour_results.setStyleSheet("font-family:monospace")
        self.contour_results.setPlainText(
            "This tab is OPTIONAL - only use if you have contour reference lines.\n\n"
            "Workflow:\n"
            "1. Convert DXF (if needed) OR directly select shapefile\n"
            "2. Detect mismatches between your data and contours\n"
            "3. Apply corrections to align with contours\n\n"
            "After contour corrections, go to tab 5 (Verify) to check results."
        )
        layout.addWidget(self.contour_results)
        
        widget.setLayout(layout)
        return widget
    
    def tab_verify(self):
        """Verification/Quality Check tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Info
        info_box = QGroupBox("Quality Verification")
        info_layout = QVBoxLayout()
        info = QLabel(
            "CRITICAL: Final verification MUST show 0 differences\n\n"
            "Checks:\n"
            "• Internal nodes (all same XY must have same Z)\n"
            "• Contour alignment (if contour file provided)\n"
            "• Statistics comparison (before/after)\n\n"
            "✓ SUCCESS = 0 differences → Ready for export\n"
            "✗ FAILURE = Issues remain → Return to corrections"
        )
        info.setWordWrap(True)
        info.setStyleSheet("font-weight:bold;background:#e3f2fd;padding:10px;border-radius:4px")
        info_layout.addWidget(info)
        info_box.setLayout(info_layout)
        layout.addWidget(info_box)
        
        # Before/After Statistics
        stats_box = QGroupBox("Statistics Summary")
        stats_layout = QVBoxLayout()
        self.stats_display = QTextEdit()
        self.stats_display.setReadOnly(True)
        self.stats_display.setMaximumHeight(150)
        self.stats_display.setStyleSheet("background:#f5f5f5;font-family:monospace")
        self.stats_display.setPlainText("Run detection and corrections first...")
        stats_layout.addWidget(self.stats_display)
        stats_box.setLayout(stats_layout)
        layout.addWidget(stats_box)
        
        # Verify button
        self.verify_btn = QPushButton("RUN FINAL VERIFICATION")
        self.verify_btn.setMinimumHeight(50)
        self.verify_btn.setStyleSheet("font-weight:bold;font-size:16px")
        self.verify_btn.clicked.connect(self.run_verification)
        self.verify_btn.setEnabled(False)
        layout.addWidget(self.verify_btn)
        
        # Results with color coding
        self.verify_results = QTextEdit()
        self.verify_results.setReadOnly(True)
        self.verify_results.setStyleSheet("font-family:monospace")
        layout.addWidget(self.verify_results)
        
        widget.setLayout(layout)
        return widget
    
    def tab_export(self):
        """Export tab"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        info = QLabel(
            "Only export after verification shows 0 differences!\n\n"
            "Export includes:\n"
            "• Corrected shapefile\n"
            "• Detailed correction log (CSV)\n"
            "• Statistics summary (TXT)"
        )
        info.setWordWrap(True)
        info.setStyleSheet("background:#fff3e0;padding:10px;border-radius:4px")
        layout.addWidget(info)
        
        # CRS Selection
        crs_group = QGroupBox("Coordinate Reference System (CRS)")
        crs_layout = QVBoxLayout()
        
        # Radio buttons for CRS choice
        self.crs_option_group = QButtonGroup()
        
        self.crs_original = QRadioButton("Use original layer CRS (recommended)")
        self.crs_original.setChecked(True)
        self.crs_original.setToolTip("Export using the same CRS as the input layers")
        self.crs_option_group.addButton(self.crs_original)
        crs_layout.addWidget(self.crs_original)
        
        self.crs_custom = QRadioButton("Use custom CRS:")
        self.crs_option_group.addButton(self.crs_custom)
        crs_layout.addWidget(self.crs_custom)
        
        # CRS selector widget
        crs_select_layout = QHBoxLayout()
        crs_select_layout.addSpacing(30)  # Indent
        
        self.crs_selector = QgsProjectionSelectionWidget()
        self.crs_selector.setEnabled(False)
        self.crs_selector.setOptionVisible(QgsProjectionSelectionWidget.CurrentCrs, True)
        self.crs_selector.setOptionVisible(QgsProjectionSelectionWidget.ProjectCrs, True)
        self.crs_selector.setOptionVisible(QgsProjectionSelectionWidget.DefaultCrs, True)
        self.crs_selector.setOptionVisible(QgsProjectionSelectionWidget.RecentCrs, True)
        self.crs_selector.setOptionVisible(QgsProjectionSelectionWidget.CrsNotSet, False)
        
        # Set default to project CRS
        self.crs_selector.setCrs(QgsProject.instance().crs())
        
        crs_select_layout.addWidget(QLabel("Selected CRS:"))
        crs_select_layout.addWidget(self.crs_selector)
        crs_layout.addLayout(crs_select_layout)
        
        # Enable/disable selector based on radio button
        self.crs_custom.toggled.connect(self.crs_selector.setEnabled)
        
        # Show current selection
        self.crs_display = QLabel()
        self.crs_display.setStyleSheet("padding:5px;background:#f5f5f5;font-size:10px")
        self.update_crs_display()
        crs_layout.addWidget(self.crs_display)
        
        # Connect to update display
        self.crs_original.toggled.connect(self.update_crs_display)
        self.crs_selector.crsChanged.connect(self.update_crs_display)
        
        crs_group.setLayout(crs_layout)
        layout.addWidget(crs_group)
        
        # Add to Map Option
        add_to_map_group = QGroupBox("Map Display Options")
        add_to_map_layout = QVBoxLayout()
        
        self.add_to_map_checkbox = QCheckBox("Add exported layers to map after export")
        self.add_to_map_checkbox.setChecked(True)  # Enabled by default
        self.add_to_map_checkbox.setToolTip("Automatically load the exported shapefiles into the current QGIS project")
        add_to_map_layout.addWidget(self.add_to_map_checkbox)
        
        add_to_map_info = QLabel("When enabled, exported layers will appear in the Layers panel after export completes.")
        add_to_map_info.setStyleSheet("color:#666;font-style:italic;font-size:10px;padding:5px")
        add_to_map_layout.addWidget(add_to_map_info)
        
        add_to_map_group.setLayout(add_to_map_layout)
        layout.addWidget(add_to_map_group)
        
        # Export button
        self.export_btn = QPushButton("EXPORT FINAL SHAPEFILE + REPORTS")
        self.export_btn.setMinimumHeight(50)
        self.export_btn.setStyleSheet("font-weight:bold;font-size:16px")
        self.export_btn.clicked.connect(self.do_export)
        self.export_btn.setEnabled(False)
        layout.addWidget(self.export_btn)
        
        self.export_results = QTextEdit()
        self.export_results.setReadOnly(True)
        self.export_results.setStyleSheet("font-family:monospace")
        layout.addWidget(self.export_results)
        
        widget.setLayout(layout)
        return widget
    
    # ========== FILE SELECTION ==========
    
    # ========== INPUT OPTION TOGGLE ==========
    
    def toggle_input_options(self):
        """Toggle between DXF (Option A) and Layers (Option B)"""
        if self.option_dxf.isChecked():
            # Show DXF option, hide Layers option
            self.grp_dxf.setVisible(True)
            self.grp_layers.setVisible(False)
        else:
            # Show Layers option, hide DXF option
            self.grp_dxf.setVisible(False)
            self.grp_layers.setVisible(True)
    
    # ========== FILE SELECTION ==========
    
    def select_dxf(self):
        """Select DXF file"""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select DXF File", os.path.expanduser("~"), "DXF Files (*.dxf)"
        )
        
        if path:
            self.paths['dxf'] = path
            self.dxf_display.setPlainText(path)
            self.dxf_display.setStyleSheet("background:#f5f5f5;border:1px solid #999")
            self.convert_btn.setEnabled(True)
            self.convert_btn.setStyleSheet("font-weight:bold")
            self.update_status(f"✓ DXF selected: {os.path.basename(path)}", "success")
            self.validate_inputs()
    
    def duplicate_selected_layers(self):
        """Create duplicates of selected layers to work on safely"""
        layers = self.get_selected_layers()
        if not layers:
            QMessageBox.warning(self, "No Selection", "Please select layers to duplicate")
            return
        
        duplicated = []
        
        for layer in layers:
            # Create duplicate
            duplicate = layer.clone()
            duplicate.setName(f"{layer.name()}_WORKING_COPY")
            
            # Add to project
            QgsProject.instance().addMapLayer(duplicate)
            
            # Track the relationship
            self.duplicated_layers[layer.id()] = duplicate.id()
            
            duplicated.append(duplicate.name())
        
        # Refresh layer list
        self.load_layers()
        
        # Auto-select the duplicated layers
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            layer = item.data(Qt.UserRole)
            if layer and layer.name().endswith("_WORKING_COPY"):
                item.setSelected(True)
        
        self.update_layer_summary()
        
        QMessageBox.information(self, "Layers Duplicated",
            f"Created {len(duplicated)} working copies:\n\n" +
            "\n".join([f"• {name}" for name in duplicated]) +
            "\n\nThese copies are now selected.\nOriginal layers remain untouched.")
    
    def select_output(self):
        """Select output folder"""
        path = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", os.path.expanduser("~")
        )
        
        if path:
            self.paths['output'] = path
            self.output_display.setPlainText(path)
            self.output_display.setStyleSheet("background:#f5f5f5;border:1px solid #999")
            self.update_status(f"✓ Output folder: {path}", "success")
            self.validate_inputs()
    
    def select_contour(self):
        """Select contour file"""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Contour Shapefile", os.path.expanduser("~"), "Shapefiles (*.shp)"
        )
        
        if path:
            self.paths['contour'] = path
            self.contour_display.setPlainText(path)
            self.contour_display.setStyleSheet("background:#f5f5f5;border:1px solid #999")
            self.update_status(f"✓ Contour file: {os.path.basename(path)}", "success")
            # Enable contour detection
            self.detect_contour_btn.setEnabled(True)
    
    def convert_dxf_to_shapefile(self):
        """Convert DXF contour file to Shapefile format"""
        # Select DXF file
        dxf_path, _ = QFileDialog.getOpenFileName(
            self, "Select DXF Contour File", os.path.expanduser("~"), "DXF Files (*.dxf)"
        )
        
        if not dxf_path:
            return
        
        # Check if output folder is set
        if not self.paths['output']:
            QMessageBox.warning(
                self, 
                "Output Folder Required", 
                "Please select an output folder first before converting DXF files."
            )
            return
        
        self.update_status("Converting DXF to Shapefile...", "processing")
        self.show_progress(True, "Converting DXF to Shapefile...", 0, 100)
        QApplication.processEvents()
        
        try:
            # Load DXF as vector layer
            dxf_layer = QgsVectorLayer(dxf_path, "temp_dxf", "ogr")
            
            if not dxf_layer.isValid():
                raise Exception("Failed to load DXF file. Please check if it's a valid DXF file.")
            
            self.show_progress(True, "Loading DXF layers...", 20, 100)
            QApplication.processEvents()
            
            # Get all sublayers (DXF files can have multiple layers)
            sublayers = dxf_layer.dataProvider().subLayers()
            
            if not sublayers:
                # No sublayers, use the main layer
                sublayers = [None]
            
            # Ask user which layers to convert
            layer_options = []
            if len(sublayers) > 1:
                for sublayer in sublayers:
                    if sublayer:
                        parts = sublayer.split('!!::!!')
                        if len(parts) >= 2:
                            layer_name = parts[1]
                            layer_options.append(layer_name)
                
                if layer_options:
                    item, ok = QInputDialog.getItem(
                        self,
                        "Select DXF Layer",
                        "The DXF file contains multiple layers.\nSelect the contour layer to convert:",
                        layer_options,
                        0,
                        False
                    )
                    
                    if not ok:
                        self.show_progress(False)
                        self.update_status("Conversion cancelled", "warning")
                        return
                    
                    # Find the corresponding sublayer
                    selected_index = layer_options.index(item)
                    selected_sublayer = sublayers[selected_index]
                    
                    # Load the specific sublayer
                    dxf_layer = QgsVectorLayer(f"{dxf_path}|layername={item}", item, "ogr")
            
            self.show_progress(True, "Processing geometries...", 40, 100)
            QApplication.processEvents()
            
            if not dxf_layer.isValid() or dxf_layer.featureCount() == 0:
                raise Exception("The selected DXF layer is empty or invalid.")
            
            # Filter only line geometries
            line_features = []
            for feature in dxf_layer.getFeatures():
                geom = feature.geometry()
                if geom and geom.type() == QgsWkbTypes.LineGeometry:
                    line_features.append(feature)
            
            if not line_features:
                raise Exception("No line geometries found in the DXF file.")
            
            self.show_progress(True, f"Found {len(line_features)} line features...", 60, 100)
            QApplication.processEvents()
            
            # Create output shapefile path
            base_name = os.path.splitext(os.path.basename(dxf_path))[0]
            output_path = os.path.join(self.paths['output'], f"{base_name}_contours.shp")
            
            # Check if file exists
            if os.path.exists(output_path):
                reply = QMessageBox.question(
                    self,
                    "File Exists",
                    f"The file {os.path.basename(output_path)} already exists.\nOverwrite?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    self.show_progress(False)
                    self.update_status("Conversion cancelled", "warning")
                    return
            
            self.show_progress(True, "Creating shapefile...", 80, 100)
            QApplication.processEvents()
            
            # Write to shapefile
            fields = dxf_layer.fields()
            crs = dxf_layer.crs()
            
            writer = QgsVectorFileWriter(
                output_path,
                "UTF-8",
                fields,
                QgsWkbTypes.LineString,
                crs,
                "ESRI Shapefile"
            )
            
            if writer.hasError() != QgsVectorFileWriter.NoError:
                raise Exception(f"Error creating shapefile: {writer.errorMessage()}")
            
            # Write features
            for feature in line_features:
                writer.addFeature(feature)
            
            del writer  # Flush to disk
            
            self.show_progress(True, "Conversion complete!", 100, 100)
            QApplication.processEvents()
            
            # Ask if user wants to load the converted file as contour
            reply = QMessageBox.question(
                self,
                "Conversion Successful",
                f"DXF file converted successfully!\n\nOutput: {os.path.basename(output_path)}\n"
                f"Features: {len(line_features)}\n\n"
                "Would you like to load this file as your contour reference?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.paths['contour'] = output_path
                self.contour_display.setPlainText(output_path)
                self.contour_display.setStyleSheet("background:#f5f5f5;border:1px solid #999")
                self.update_status(f"✓ Contour file loaded: {os.path.basename(output_path)}", "success")
                self.detect_contour_btn.setEnabled(True)
            else:
                self.update_status(f"✓ Conversion complete: {os.path.basename(output_path)}", "success")
            
            self.show_progress(False)
            
        except Exception as e:
            self.show_progress(False)
            QMessageBox.critical(
                self,
                "Conversion Error",
                f"Failed to convert DXF file:\n\n{str(e)}"
            )
            self.update_status(f"✗ Conversion failed: {str(e)}", "error")

    
    def load_layers(self):
        """Load available line layers into list widget"""
        self.layer_list.clear()
        
        count = 0
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.geometryType() == QgsWkbTypes.LineGeometry:
                item = QListWidgetItem(layer.name())
                item.setData(Qt.UserRole, layer)  # Store layer object
                self.layer_list.addItem(item)
                count += 1
        
        if count == 0:
            item = QListWidgetItem("(No line layers found)")
            item.setFlags(Qt.ItemIsEnabled)  # Not selectable
            self.layer_list.addItem(item)
        
        self.update_layer_summary()
        self.update_crs_display()  # Update CRS display
    
    def select_all_layers(self):
        """Select all layers in the list"""
        for i in range(self.layer_list.count()):
            item = self.layer_list.item(i)
            if item.flags() & Qt.ItemIsSelectable:
                item.setSelected(True)
        self.update_layer_summary()
    
    def clear_layer_selection(self):
        """Clear all layer selections"""
        self.layer_list.clearSelection()
        self.update_layer_summary()
    
    def update_layer_summary(self):
        """Update the layer selection summary label"""
        selected = self.get_selected_layers()
        count = len(selected)
        
        if count == 0:
            self.layer_summary.setText("No layers selected")
            self.layer_summary.setStyleSheet("padding:5px;background:#ffebee;border:1px solid #ccc;border-radius:3px;font-size:11px")
        elif count == 1:
            self.layer_summary.setText(f"✓ 1 layer selected: {selected[0].name()}")
            self.layer_summary.setStyleSheet("padding:5px;background:#e8f5e9;border:1px solid #4CAF50;border-radius:3px;font-size:11px")
        else:
            names = ", ".join([layer.name() for layer in selected[:3]])
            if count > 3:
                names += f", ... (+{count-3} more)"
            self.layer_summary.setText(f"✓ {count} layers selected: {names}")
            self.layer_summary.setStyleSheet("padding:5px;background:#e8f5e9;border:1px solid #4CAF50;border-radius:3px;font-size:11px")
        
        self.validate_inputs()
    
    def get_selected_layers(self):
        """Get list of selected layer objects"""
        layers = []
        for item in self.layer_list.selectedItems():
            layer = item.data(Qt.UserRole)
            if layer:
                layers.append(layer)
        return layers
    
    def get_layer(self):
        """Get working layer - returns first selected layer for compatibility"""
        layers = self.get_selected_layers()
        return layers[0] if layers else None
    
    def validate_inputs(self):
        """Enable/disable buttons based on inputs"""
        layers = self.get_selected_layers()
        has_layer = len(layers) > 0
        has_output = bool(self.paths['output'])
        
        # Enable duplicate button if layers selected
        if hasattr(self, 'duplicate_layers_btn'):
            self.duplicate_layers_btn.setEnabled(has_layer)
        
        # Enable detection if we have layer and output
        if hasattr(self, 'detect_btn'):
            self.detect_btn.setEnabled(has_layer and has_output)
        
        # Update correction options visibility
        self.update_correction_options_visibility()
        
        if has_layer and has_output:
            self.update_status("✓ Ready to detect issues", "success")
        elif has_layer:
            self.update_status("⚠ Select output folder to continue", "warning")
        else:
            self.update_status("⚠ Select a layer to continue", "warning")
    
    def update_correction_options_visibility(self):
        """Show/hide correction options based on available data"""
        if not hasattr(self, 'external_group'):
            return  # Correction tab not created yet
        
        layers = self.get_selected_layers()
        
        # External corrections: only show if multiple layers selected
        if len(layers) > 1:
            self.external_group.setVisible(True)
        else:
            self.external_group.setVisible(False)
        
        # Internal corrections: always visible
        # (no change needed, always shown)
    
    # ========== CONVERSION ==========
    
    def do_convert(self):
        """Convert DXF to shapefile"""
        if not self.paths['dxf'] or not self.paths['output']:
            QMessageBox.warning(self, "Missing Files", "Select DXF and output folder")
            return
        
        try:
            self.update_status("Converting DXF...", "processing")
            self.show_progress(True, "Converting DXF to shapefile...", 0, 0)
            QApplication.processEvents()
            
            # DXF files can contain multiple geometry types
            # We'll try to load and filter for line geometries
            dxf_layer = QgsVectorLayer(self.paths['dxf'], "temp_dxf", "ogr")
            if not dxf_layer.isValid():
                raise Exception("Cannot read DXF file. Make sure it's a valid DXF file.")
            
            # Check geometry type
            geom_type = dxf_layer.geometryType()
            geom_type_name = ["Point", "Line", "Polygon"][geom_type]
            
            self.show_progress(True, f"Converting {geom_type_name} features...", 0, 0)
            QApplication.processEvents()
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            base_name = os.path.splitext(os.path.basename(self.paths['dxf']))[0]
            output_file = os.path.join(self.paths['output'], f"{base_name}_converted_{timestamp}.shp")
            
            # Convert to shapefile
            error = QgsVectorFileWriter.writeAsVectorFormat(
                dxf_layer, 
                output_file, 
                "UTF-8", 
                dxf_layer.crs(), 
                "ESRI Shapefile"
            )
            
            if error[0] != QgsVectorFileWriter.NoError:
                raise Exception(f"Conversion failed: {error[1]}")
            
            # Load into QGIS
            layer_name = f"{base_name}_converted"
            new_layer = QgsVectorLayer(output_file, layer_name, "ogr")
            
            if not new_layer.isValid():
                raise Exception("Converted file is not valid")
            
            # Add to project
            QgsProject.instance().addMapLayer(new_layer)
            
            # Refresh layer list
            self.load_layers()
            
            # Auto-select the new layer if it's a line layer
            layer_was_selected = False
            if new_layer.geometryType() == QgsWkbTypes.LineGeometry:
                for i in range(self.layer_list.count()):
                    item = self.layer_list.item(i)
                    layer = item.data(Qt.UserRole)
                    if layer and layer.name() == layer_name:
                        item.setSelected(True)
                        # Make it visually prominent
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                        item.setBackground(QColor("#e8f5e9"))  # Light green
                        layer_was_selected = True
                        break
                
                # Update layer summary to show selection
                self.update_layer_summary()
                
                # Also switch to Option B to show the selected layer
                self.option_layers.setChecked(True)
            
            self.show_progress(False)
            
            # Update status with clear next step
            if layer_was_selected:
                self.update_status("✓ Conversion complete - Layer selected → Go to Detection tab", "success")
            else:
                self.update_status("✓ Conversion complete", "success")
            
            # Check if it has Z coordinates
            has_z = QgsWkbTypes.hasZ(new_layer.wkbType())
            z_info = "✓ Has Z coordinates" if has_z else "⚠ No Z coordinates found"
            
            selection_msg = ""
            if layer_was_selected:
                selection_msg = "\n✓ Layer auto-selected in Option B\n✓ Ready to proceed to Detection tab"
            
            QMessageBox.information(self, "Conversion Complete", 
                f"Successfully converted DXF to shapefile!\n\n"
                f"File: {os.path.basename(output_file)}\n"
                f"Type: {geom_type_name}\n"
                f"Features: {new_layer.featureCount()}\n"
                f"{z_info}"
                f"{selection_msg}")
            
        except Exception as e:
            self.show_progress(False)
            self.update_status(f"✗ Conversion failed", "error")
            QMessageBox.critical(self, "Conversion Error", 
                f"Failed to convert DXF file:\n\n{str(e)}\n\n"
                f"Common issues:\n"
                f"• DXF file is corrupted or invalid\n"
                f"• DXF contains unsupported elements\n"
                f"• File is locked by another program")
            import traceback
            traceback.print_exc()
    
    # ========== DETECTION ==========
    
    def run_detection(self):
        """Detect problem nodes with progress tracking - supports multiple layers"""
        layers = self.get_selected_layers()
        if not layers:
            QMessageBox.warning(self, "No Layer", "Select at least one layer")
            return
        
        if not self.paths['output']:
            QMessageBox.warning(self, "No Output", "Select output folder first")
            return
        
        # Check all layers have Z coordinates
        for layer in layers:
            if not QgsWkbTypes.hasZ(layer.wkbType()):
                QMessageBox.critical(self, "No Z", f"Layer '{layer.name()}' has no Z coordinates")
                return
        
        self.detect_results.clear()
        self.detect_stats_display.clear()
        self.update_status("Analyzing nodes across layers...", "processing")
        
        start_time = time.time()
        total_features = sum(layer.featureCount() for layer in layers)
        
        # Display layer info
        self.detect_results.append("=" * 70 + "\n")
        self.detect_results.append("ANALYZING MULTIPLE LAYERS\n")
        self.detect_results.append("=" * 70 + "\n\n")
        self.detect_results.append(f"Number of layers: {len(layers)}\n")
        for i, layer in enumerate(layers, 1):
            self.detect_results.append(f"  {i}. {layer.name()} ({layer.featureCount()} features)\n")
        self.detect_results.append(f"Total features: {total_features}\n\n")
        
        # Phase 1: Insert intersection vertices if requested
        if self.detect_intersections_cb.isChecked():
            self.detect_results.append("=" * 70 + "\n")
            self.detect_results.append("PHASE 1: INTERSECTION DETECTION (WITHIN AND ACROSS LAYERS)\n")
            self.detect_results.append("=" * 70 + "\n\n")
            
            total_intersections = 0
            
            # Check intersections within each layer
            for layer in layers:
                intersections_added = self.detect_and_insert_intersections(layer)
                total_intersections += intersections_added
                if intersections_added > 0:
                    layer.commitChanges()
                    layer.updateExtents()
            
            # Check intersections BETWEEN layers
            for i, layer1 in enumerate(layers):
                for layer2 in layers[i+1:]:
                    intersections_added = self.detect_intersections_between_layers(layer1, layer2)
                    total_intersections += intersections_added
            
            self.detect_results.append(f"Total intersections found and vertices inserted: {total_intersections}\n\n")
            
            if total_intersections > 0:
                self.iface.mapCanvas().refresh()
        
        # Phase 2: Detect Z differences ACROSS ALL LAYERS
        self.detect_results.append("=" * 70 + "\n")
        self.detect_results.append("PHASE 2: Z-COORDINATE ANALYSIS (ACROSS ALL LAYERS)\n")
        self.detect_results.append("=" * 70 + "\n\n")
        
        self.show_progress(True, "Analyzing vertices across layers...", 0, total_features)
        
        # Collect all vertices from ALL layers
        nodes = defaultdict(list)
        processed = 0
        
        for layer in layers:
            for feat in layer.getFeatures():
                geom = feat.geometry()
                if not geom.isEmpty():
                    coords = self.parse_wkt(geom.asWkt())
                    for x, y, z in coords:
                        if abs(z) > 1e-10:
                            nodes[(x, y)].append({
                                'layer': layer.name(),
                                'layer_id': layer.id(),
                                'fid': feat.id(),
                                'z': z
                            })
                
                processed += 1
                if processed % 100 == 0:
                    self.show_progress(True, f"Analyzing vertices... ({processed}/{total_features})", processed, total_features)
                    QApplication.processEvents()
            if processed % 100 == 0:
                self.show_progress(True, f"Analyzing vertices... ({processed}/{total_features})", processed, total_features)
                QApplication.processEvents()
        
        # Find problems
        self.show_progress(True, "Analyzing Z differences...", 0, 0)
        QApplication.processEvents()
        
        problems = []
        for (x, y), entries in nodes.items():
            if len(entries) > 1:
                zvals = [e['z'] for e in entries]
                if len(set(zvals)) > 1:
                    problems.append({
                        'x': x, 'y': y,
                        'entries': entries,
                        'z_min': min(zvals),
                        'z_max': max(zvals),
                        'z_diff': max(zvals) - min(zvals)
                    })
        
        self.nodes_csv = problems
        elapsed_time = time.time() - start_time
        
        # Store statistics
        self.detection_stats = {
            'total_nodes': len(nodes),
            'problem_nodes': len(problems),
            'total_features': total_features,
            'detection_time': elapsed_time
        }
        
        # Update statistics display
        self.detect_stats_display.append(f"Total features: {total_features}\n")
        self.detect_stats_display.append(f"Total nodes: {len(nodes)}\n")
        self.detect_stats_display.append(f"Problem nodes: {len(problems)}\n")
        self.detect_stats_display.append(f"Detection time: {elapsed_time:.2f}s\n")
        
        # Show results
        self.detect_results.append(f"Total nodes analyzed: {len(nodes)}\n")
        self.detect_results.append(f"Nodes with Z differences: {len(problems)}\n")
        self.detect_results.append(f"Processing time: {elapsed_time:.2f} seconds\n\n")
        
        if problems:
            # Calculate statistics
            max_diff = max(p['z_diff'] for p in problems)
            avg_diff = sum(p['z_diff'] for p in problems) / len(problems)
            
            self.detect_results.append(f"Maximum Z difference: {max_diff:.3f}\n")
            self.detect_results.append(f"Average Z difference: {avg_diff:.3f}\n\n")
            
            self.detect_results.append("Sample issues (showing first 15):\n")
            self.detect_results.append("-" * 70 + "\n")
            for i, p in enumerate(problems[:15], 1):
                self.detect_results.append(
                    f"{i:2d}. ({p['x']:.2f}, {p['y']:.2f}): "
                    f"Z range [{p['z_min']:.2f} to {p['z_max']:.2f}] "
                    f"diff={p['z_diff']:.3f}\n"
                )
            
            if len(problems) > 15:
                self.detect_results.append(f"\n... and {len(problems) - 15} more issues\n")
            
            # Save detailed CSV
            csv_file = os.path.join(
                self.paths['output'], 
                f"detected_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
            with open(csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['X', 'Y', 'FID', 'Z', 'Z_Min', 'Z_Max', 'Z_Diff'])
                for p in problems:
                    for e in p['entries']:
                        writer.writerow([
                            p['x'], p['y'], e['fid'], e['z'], 
                            p['z_min'], p['z_max'], p['z_diff']
                        ])
            
            self.detect_results.append(f"\nDetailed CSV saved: {csv_file}\n")
            
            # Enable correction buttons
            self.correct_internal_btn.setEnabled(True)
            
            # Enable external button if multiple layers selected
            if len(layers) > 1:
                self.correct_external_btn.setEnabled(True)
            
            if self.paths['contour']:
                self.correct_contour_btn.setEnabled(True)
                self.correct_contour_btn.setStyleSheet("background:#ff9800;color:white;font-weight:bold")
            
            self.update_status(f"⚠ Found {len(problems)} problem nodes - Apply corrections", "warning")
        else:
            self.detect_results.append("✓ No problems found - All nodes have consistent Z values!\n")
            self.update_status("✓ Perfect data - No corrections needed", "success")
            self.verify_btn.setEnabled(True)
            self.export_btn.setEnabled(True)
        
        # Enable export nodes button if problems were found
        if self.nodes_csv:
            self.export_nodes_btn.setEnabled(True)
        
        self.show_progress(False)
    
    def export_problem_nodes(self):
        """Export problem nodes as point shapefile for visualization"""
        if not self.nodes_csv:
            QMessageBox.warning(self, "No Data", "Run detection first")
            return
        
        if not self.paths['output']:
            QMessageBox.warning(self, "No Output Folder", "Select output folder first")
            return
        
        self.update_status("Exporting problem nodes...", "processing")
        self.show_progress(True, "Creating point shapefile...", 0, len(self.nodes_csv))
        
        try:
            # Create output filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_file = os.path.join(self.paths['output'], f"PROBLEM_NODES_{timestamp}.shp")
            
            # Get CRS from layers
            layers = self.get_selected_layers()
            crs = layers[0].crs() if layers else QgsProject.instance().crs()
            
            # Define fields
            fields = QgsFields()
            fields.append(QgsField("node_id", QVariant.Int))
            fields.append(QgsField("x", QVariant.Double))
            fields.append(QgsField("y", QVariant.Double))
            fields.append(QgsField("z_min", QVariant.Double))
            fields.append(QgsField("z_max", QVariant.Double))
            fields.append(QgsField("z_diff", QVariant.Double))
            fields.append(QgsField("count", QVariant.Int))
            fields.append(QgsField("layers", QVariant.String))
            fields.append(QgsField("severity", QVariant.String))
            
            # Create temporary memory layer first
            temp_layer = QgsVectorLayer(f"PointZ?crs={crs.authid()}", "temp_nodes", "memory")
            temp_provider = temp_layer.dataProvider()
            temp_provider.addAttributes(fields)
            temp_layer.updateFields()
            
            # Add features to memory layer
            features = []
            for idx, node in enumerate(self.nodes_csv):
                x = node['x']
                y = node['y']
                z_min = node['z_min']
                z_max = node['z_max']
                z_diff = z_max - z_min
                
                # Determine severity
                if z_diff < 0.1:
                    severity = "Minor"
                elif z_diff < 0.5:
                    severity = "Medium"
                elif z_diff < 1.0:
                    severity = "High"
                else:
                    severity = "Critical"
                
                # Get unique layer names
                layer_names = set(entry.get('layer', 'Unknown') for entry in node['entries'])
                layers_str = ", ".join(sorted(layer_names))
                if len(layers_str) > 254:  # Shapefile field limit
                    layers_str = layers_str[:250] + "..."
                
                # Create point geometry
                point = QgsPoint(x, y, z_min)  # Use minimum Z
                geom = QgsGeometry(point)
                
                # Create feature
                feat = QgsFeature()
                feat.setGeometry(geom)
                feat.setAttributes([
                    idx + 1,           # node_id
                    x,                 # x
                    y,                 # y
                    z_min,             # z_min
                    z_max,             # z_max
                    z_diff,            # z_diff
                    len(node['entries']),  # count
                    layers_str,        # layers
                    severity           # severity
                ])
                
                features.append(feat)
                
                if idx % 100 == 0:
                    self.show_progress(True, f"Creating points... ({idx}/{len(self.nodes_csv)})", 
                                     idx, len(self.nodes_csv))
                    QApplication.processEvents()
            
            # Add all features at once
            temp_provider.addFeatures(features)
            
            # Write to shapefile using the simpler API
            error = QgsVectorFileWriter.writeAsVectorFormat(
                temp_layer,
                output_file,
                "UTF-8",
                crs,
                "ESRI Shapefile"
            )
            
            if error[0] != QgsVectorFileWriter.NoError:
                raise Exception(f"Error writing shapefile: {error[1]}")
            
            # Load the shapefile into QGIS
            point_layer = QgsVectorLayer(output_file, f"Problem Nodes {timestamp}", "ogr")
            
            if not point_layer.isValid():
                raise Exception("Created shapefile is not valid")
            
            # Apply categorized styling by severity
            self.style_problem_nodes(point_layer)
            QgsProject.instance().addMapLayer(point_layer)
            
            # Zoom to layer
            self.iface.mapCanvas().setExtent(point_layer.extent())
            self.iface.mapCanvas().refresh()
            
            self.show_progress(False)
            self.update_status(f"✓ Exported {len(self.nodes_csv)} problem nodes", "success")
            
            QMessageBox.information(self, "Export Complete",
                f"Problem nodes exported successfully!\n\n"
                f"File: {os.path.basename(output_file)}\n"
                f"Points: {len(self.nodes_csv)}\n\n"
                f"The point layer has been added to your map and styled by severity:\n"
                f"• Green: Minor (< 0.1m difference)\n"
                f"• Yellow: Medium (0.1-0.5m)\n"
                f"• Orange: High (0.5-1.0m)\n"
                f"• Red: Critical (> 1.0m)")
            
        except Exception as e:
            self.show_progress(False)
            self.update_status("✗ Export failed", "error")
            QMessageBox.critical(self, "Export Error", f"Failed to export nodes:\n\n{str(e)}")
            import traceback
            traceback.print_exc()
    
    def style_problem_nodes(self, layer):
        """Apply categorized styling to problem nodes layer based on severity"""
        # Define categories with colors
        categories = [
            ("Minor", "#4CAF50"),      # Green
            ("Medium", "#FFC107"),     # Yellow
            ("High", "#FF9800"),       # Orange
            ("Critical", "#F44336")    # Red
        ]
        
        category_list = []
        for label, color in categories:
            symbol = QgsMarkerSymbol.createSimple({
                'name': 'circle',
                'color': color,
                'size': '4',
                'outline_color': 'black',
                'outline_width': '0.5'
            })
            category = QgsRendererCategory(label, symbol, label)
            category_list.append(category)
        
        # Create renderer
        renderer = QgsCategorizedSymbolRenderer('severity', category_list)
        layer.setRenderer(renderer)
        layer.triggerRepaint()
    
    def detect_and_insert_intersections(self, layer):
        """Detect line intersections and insert vertices at EXACT crossing points with MINIMUM Z value"""
        tolerance = self.intersection_tolerance.value()
        features = list(layer.getFeatures())
        total = len(features)
        
        self.show_progress(True, "Finding intersections...", 0, total)
        
        # STEP 1: Find all intersections and collect the changes we need to make
        # Don't modify geometries yet - just collect what needs to be changed
        changes_to_apply = []  # List of (fid, new_geometry)
        
        for i, feat1 in enumerate(features):
            fid1 = feat1.id()
            geom1 = feat1.geometry()
            
            for j, feat2 in enumerate(features[i+1:], i+1):
                fid2 = feat2.id()
                geom2 = feat2.geometry()
                
                if geom1.intersects(geom2):
                    intersection = geom1.intersection(geom2)
                    
                    if intersection.type() == QgsWkbTypes.PointGeometry:
                        points = [intersection.asPoint()] if not intersection.isMultipart() else intersection.asMultiPoint()
                        
                        for pt in points:
                            # Get Z values from both lines at crossing
                            z1_at_crossing = self.get_z_at_exact_point_on_line(geom1, pt.x(), pt.y())
                            z2_at_crossing = self.get_z_at_exact_point_on_line(geom2, pt.x(), pt.y())
                            
                            # Use MINIMUM Z value
                            z_min = min(z1_at_crossing, z2_at_crossing)
                            
                            # Check if we need to insert vertex on geom1
                            if not self.vertex_exists(geom1, pt.x(), pt.y(), tolerance):
                                new_geom1 = self.insert_vertex_at_exact_point(geom1, pt.x(), pt.y(), z_min, tolerance)
                                if new_geom1:
                                    changes_to_apply.append((fid1, new_geom1))
                                    geom1 = new_geom1  # Update for subsequent checks in this loop
                            
                            # Check if we need to insert vertex on geom2
                            if not self.vertex_exists(geom2, pt.x(), pt.y(), tolerance):
                                new_geom2 = self.insert_vertex_at_exact_point(geom2, pt.x(), pt.y(), z_min, tolerance)
                                if new_geom2:
                                    changes_to_apply.append((fid2, new_geom2))
                                    geom2 = new_geom2  # Update for subsequent checks in this loop
            
            if i % 10 == 0:
                self.show_progress(True, f"Finding intersections... ({i}/{total})", i, total)
                QApplication.processEvents()
        
        # STEP 2: Now apply all the changes
        # Group changes by FID (a feature might need multiple vertex insertions)
        if changes_to_apply:
            self.show_progress(True, "Applying geometry changes...", 0, len(changes_to_apply))
            
            layer.startEditing()
            
            # Group by FID and use the last geometry change for each feature
            fid_to_geom = {}
            for fid, geom in changes_to_apply:
                fid_to_geom[fid] = geom
            
            # Apply changes
            applied = 0
            for fid, new_geom in fid_to_geom.items():
                try:
                    if layer.changeGeometry(fid, new_geom):
                        applied += 1
                except:
                    # Skip features that can't be changed
                    pass
                
                if applied % 10 == 0:
                    self.show_progress(True, f"Applying changes... ({applied}/{len(fid_to_geom)})", applied, len(fid_to_geom))
                    QApplication.processEvents()
            
            return applied
        
        return 0
    
    def detect_intersections_between_layers(self, layer1, layer2):
        """Detect intersections BETWEEN two different layers and insert vertices"""
        tolerance = self.intersection_tolerance.value()
        features1 = list(layer1.getFeatures())
        features2 = list(layer2.getFeatures())
        
        self.show_progress(True, f"Finding intersections: {layer1.name()} × {layer2.name()}...", 0, len(features1))
        
        # STEP 1: Find all intersections and collect changes
        changes_layer1 = []  # (fid, new_geometry)
        changes_layer2 = []  # (fid, new_geometry)
        
        for i, feat1 in enumerate(features1):
            fid1 = feat1.id()
            geom1 = feat1.geometry()
            
            for feat2 in features2:
                fid2 = feat2.id()
                geom2 = feat2.geometry()
                
                if geom1.intersects(geom2):
                    intersection = geom1.intersection(geom2)
                    
                    if intersection.type() == QgsWkbTypes.PointGeometry:
                        points = [intersection.asPoint()] if not intersection.isMultipart() else intersection.asMultiPoint()
                        
                        for pt in points:
                            # Get Z from both lines at crossing
                            z1_at_crossing = self.get_z_at_exact_point_on_line(geom1, pt.x(), pt.y())
                            z2_at_crossing = self.get_z_at_exact_point_on_line(geom2, pt.x(), pt.y())
                            
                            # Use MINIMUM Z value
                            z_min = min(z1_at_crossing, z2_at_crossing)
                            
                            # Check if we need to insert vertex on geom1
                            if not self.vertex_exists(geom1, pt.x(), pt.y(), tolerance):
                                new_geom1 = self.insert_vertex_at_exact_point(geom1, pt.x(), pt.y(), z_min, tolerance)
                                if new_geom1:
                                    changes_layer1.append((fid1, new_geom1))
                                    geom1 = new_geom1
                            
                            # Check if we need to insert vertex on geom2
                            if not self.vertex_exists(geom2, pt.x(), pt.y(), tolerance):
                                new_geom2 = self.insert_vertex_at_exact_point(geom2, pt.x(), pt.y(), z_min, tolerance)
                                if new_geom2:
                                    changes_layer2.append((fid2, new_geom2))
                                    geom2 = new_geom2
            
            if i % 10 == 0:
                self.show_progress(True, f"Finding intersections: {layer1.name()} × {layer2.name()}... ({i}/{len(features1)})", i, len(features1))
                QApplication.processEvents()
        
        # STEP 2: Apply all changes
        total_applied = 0
        
        if changes_layer1:
            layer1.startEditing()
            fid_to_geom = {}
            for fid, geom in changes_layer1:
                fid_to_geom[fid] = geom
            
            for fid, new_geom in fid_to_geom.items():
                try:
                    if layer1.changeGeometry(fid, new_geom):
                        total_applied += 1
                except:
                    pass
            
            layer1.commitChanges()
        
        if changes_layer2:
            layer2.startEditing()
            fid_to_geom = {}
            for fid, geom in changes_layer2:
                fid_to_geom[fid] = geom
            
            for fid, new_geom in fid_to_geom.items():
                try:
                    if layer2.changeGeometry(fid, new_geom):
                        total_applied += 1
                except:
                    pass
            
            layer2.commitChanges()
        
        return total_applied
    
    def vertex_exists(self, geom, x, y, tolerance):
        """Check if vertex exists at location"""
        for vx, vy, _ in self.parse_wkt(geom.asWkt()):
            if abs(vx - x) < tolerance and abs(vy - y) < tolerance:
                return True
        return False
    
    def insert_vertex_at_exact_point(self, geom, exact_x, exact_y, z_value, tolerance):
        """Insert vertex at EXACT crossing point (no interpolation of XY coordinates)"""
        coords = self.parse_wkt(geom.asWkt())
        new_coords = []
        vertex_inserted = False
        
        for i in range(len(coords) - 1):
            p1 = coords[i]
            p2 = coords[i + 1]
            
            # Add first point of segment
            new_coords.append(p1)
            
            # Check if the EXACT point lies on this segment
            if self.point_on_segment(exact_x, exact_y, p1[0], p1[1], p2[0], p2[1], tolerance):
                # Insert vertex at EXACT XY coordinates with specified Z
                new_coords.append((exact_x, exact_y, z_value))
                vertex_inserted = True
        
        # Add last point
        new_coords.append(coords[-1])
        
        # Only return new geometry if we actually added a vertex
        if vertex_inserted and len(new_coords) > len(coords):
            coord_str = ", ".join([f"{c[0]} {c[1]} {c[2]}" for c in new_coords])
            wkt = geom.asWkt()
            if "MULTI" in wkt.upper():
                new_wkt = f"MULTILINESTRING Z (({coord_str}))"
            else:
                new_wkt = f"LINESTRING Z ({coord_str})"
            return QgsGeometry.fromWkt(new_wkt)
        
        return None
    
    def point_on_segment(self, px, py, x1, y1, x2, y2, tolerance):
        """
        Check if point is on line segment.
        Handles zero-length segments and zero tolerance properly.
        """
        # Vector from p1 to p2
        dx = x2 - x1
        dy = y2 - y1
        
        # Vector from p1 to point
        dpx = px - x1
        dpy = py - y1
        
        # Length squared
        len_sq = dx * dx + dy * dy
        
        # CRITICAL: Prevent division by zero
        # Check if segment has zero or near-zero length (p1 == p2 or nearly identical)
        if len_sq == 0.0:
            # Zero-length segment: point must be at same location
            if tolerance == 0:
                return dpx == 0.0 and dpy == 0.0
            else:
                dist_sq = dpx * dpx + dpy * dpy
                return dist_sq <= tolerance * tolerance
        
        # Parameter t
        t = (dpx * dx + dpy * dy) / len_sq
        
        # Check if point projects onto segment
        if t < 0 or t > 1:
            return False
        
        # Closest point on segment
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy
        
        # Distance from point to closest point
        dist_x = px - closest_x
        dist_y = py - closest_y
        dist_sq = dist_x * dist_x + dist_y * dist_y
        
        # Handle zero tolerance (exact matching)
        if tolerance == 0:
            return dist_sq == 0.0
        else:
            return dist_sq <= tolerance * tolerance
    
    def get_segment_parameter(self, px, py, x1, y1, x2, y2):
        """Get parameter t for point projection on segment"""
        dx = x2 - x1
        dy = y2 - y1
        dpx = px - x1
        dpy = py - y1
        len_sq = dx * dx + dy * dy
        
        if len_sq < 1e-10:
            return 0.0
        
        return (dpx * dx + dpy * dy) / len_sq
    
    def get_z_at_exact_point_on_line(self, geom, exact_x, exact_y, tolerance=1e-6):
        """
        Get Z value at EXACT XY point on line.
        
        The XY coordinates are the EXACT crossing point (not interpolated).
        The Z value is determined by:
        - If point is on an existing vertex: use that vertex's Z
        - If point is between vertices: we need to determine what Z the line has there
          We calculate this by interpolating Z along the segment
          (This is NOT adding new data - it's finding what Z the line already implies at that XY)
        
        Then we take MINIMUM of Z from both lines.
        """
        coords = self.parse_wkt(geom.asWkt())
        
        # Check if point is exactly on an existing vertex
        for x, y, z in coords:
            if abs(x - exact_x) < tolerance and abs(y - exact_y) < tolerance:
                return z
        
        # Point is between vertices - find which segment and calculate Z at that point
        for i in range(len(coords) - 1):
            p1 = coords[i]
            p2 = coords[i + 1]
            
            if self.point_on_segment(exact_x, exact_y, p1[0], p1[1], p2[0], p2[1], tolerance):
                # Point is on this segment
                # Calculate where along the segment (0 to 1)
                t = self.get_segment_parameter(exact_x, exact_y, p1[0], p1[1], p2[0], p2[1])
                
                # Calculate Z at this position
                # (This finds what Z value the line implies at this XY location)
                z_at_point = p1[2] + t * (p2[2] - p1[2])
                return z_at_point
        
        return 0.0
    
    # ========== CORRECTION ==========
    
    # ========== UNDO SYSTEM ==========
    
    def save_undo_state(self, correction_type, affected_layers):
        """
        Save current state before making corrections.
        Stores geometry snapshots of affected features.
        """
        undo_entry = {
            'type': correction_type,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'layers': []
        }
        
        for layer in affected_layers:
            layer_state = {
                'layer_id': layer.id(),
                'layer_name': layer.name(),
                'features': {}
            }
            
            # Get all features that will be modified
            for feat in layer.getFeatures():
                # Store original geometry as WKT
                layer_state['features'][feat.id()] = feat.geometry().asWkt()
            
            undo_entry['layers'].append(layer_state)
        
        # Add to stack
        self.undo_stack.append(undo_entry)
        
        # Limit stack size
        if len(self.undo_stack) > self.max_undo_levels:
            self.undo_stack.pop(0)
        
        # Update UI
        self.undo_btn.setEnabled(True)
        self.update_undo_status()
    
    def undo_last_correction(self):
        """Restore layers to state before last correction"""
        if not self.undo_stack:
            QMessageBox.warning(self, "Nothing to Undo", "No corrections to undo")
            return
        
        # Get last state
        undo_entry = self.undo_stack.pop()
        
        self.update_status("Undoing corrections...", "processing")
        self.show_progress(True, "Restoring geometries...", 0, 0)
        
        restored_count = 0
        
        for layer_state in undo_entry['layers']:
            layer = QgsProject.instance().mapLayer(layer_state['layer_id'])
            
            if not layer:
                print(f"WARNING: Layer {layer_state['layer_name']} not found")
                continue
            
            layer.startEditing()
            
            for fid, wkt in layer_state['features'].items():
                feat = layer.getFeature(fid)
                if feat.isValid():
                    restored_geom = QgsGeometry.fromWkt(wkt)
                    layer.changeGeometry(fid, restored_geom)
                    restored_count += 1
            
            layer.commitChanges()
            layer.updateExtents()
        
        self.show_progress(False)
        self.update_status(f"✓ Undone - Restored {restored_count} features", "success")
        
        # Update UI
        self.update_undo_status()
        if not self.undo_stack:
            self.undo_btn.setEnabled(False)
        
        # Refresh map
        self.iface.mapCanvas().refresh()
        
        # Remove last entry from correction history
        if self.correction_history:
            self.correction_history.pop()
            self.update_correction_summary()
        
        QMessageBox.information(self, "Undo Complete",
            f"Successfully restored {restored_count} features\n\n"
            f"Layers affected: {len(undo_entry['layers'])}")
    
    def update_undo_status(self):
        """Update undo button status text"""
        if not hasattr(self, 'undo_status'):
            return
        
        if not self.undo_stack:
            self.undo_status.setText("No corrections to undo")
        else:
            last = self.undo_stack[-1]
            self.undo_status.setText(
                f"Can undo: {last['type']} correction from {last['timestamp']}\n"
                f"({len(self.undo_stack)} correction(s) in undo history)"
            )
    
    # ========== CORRECTIONS ==========
    
    def apply_internal(self):
        """
        Apply internal corrections (Z = MINIMUM AT EACH NODE) across ALL layers.
        
        Logic:
        - For each node (XY location), find the MINIMUM Z value across all layers
        - Set ALL occurrences of that node to the MINIMUM Z
        - This ensures internal consistency: same XY = same Z
        """
        if not self.nodes_csv:
            QMessageBox.warning(self, "No Data", "Run detection first")
            return
        
        self.correct_results.clear()
        self.correct_results.append("=" * 70 + "\n")
        self.correct_results.append("INTERNAL CORRECTIONS ACROSS ALL LAYERS\n")
        self.correct_results.append("Z = MINIMUM AT EACH NODE\n")
        self.correct_results.append("=" * 70 + "\n\n")
        
        # Get all layers that will be affected
        affected_layers = []
        for node in self.nodes_csv:
            for entry in node['entries']:
                layer_id = entry['layer_id']
                layer = QgsProject.instance().mapLayer(layer_id)
                if layer and layer not in affected_layers:
                    affected_layers.append(layer)
        
        # Save undo state BEFORE making any changes
        self.save_undo_state('internal', affected_layers)
        self.correct_results.append("✓ Undo state saved\n\n")
        
        self.update_status("Applying internal corrections across all layers...", "processing")
        self.show_progress(True, "Correcting vertices...", 0, len(self.nodes_csv))
        
        # Group layers that need editing
        layers_to_edit = {}  # layer_id -> layer object
        layer_corrections = defaultdict(int)  # layer_id -> count
        
        count = 0
        corrections = []
        layers_affected = set()
        nodes_used_max = 0  # Track nodes where max was used instead of min
        
        for idx, node in enumerate(self.nodes_csv):
            x, y = node['x'], node['y']
            z_min = node['z_min']  # MINIMUM Z at this node
            z_max = node['z_max']  # MAXIMUM Z at this node
            
            # SMART Z SELECTION: If minimum is 0, use maximum instead
            # (Z=0 often indicates missing/error data)
            if z_min == 0.0 and z_max != 0.0:
                target_z = z_max
                correction_rule = "Z=MAX (min was 0)"
                nodes_used_max += 1
            else:
                target_z = z_min
                correction_rule = "Z=MIN"
            
            # Apply correction to ALL entries at this node
            for entry in node['entries']:
                # EXACT comparison - no tolerance
                if entry['z'] != target_z:
                    layer_id = entry['layer_id']
                    fid = entry['fid']
                    
                    # Get layer object
                    if layer_id not in layers_to_edit:
                        layer = QgsProject.instance().mapLayer(layer_id)
                        if layer:
                            layer.startEditing()
                            layers_to_edit[layer_id] = layer
                    
                    layer = layers_to_edit.get(layer_id)
                    if not layer:
                        print(f"WARNING: Could not find layer {layer_id}")
                        continue
                    
                    # Get feature and update Z
                    feat = layer.getFeature(fid)
                    if not feat.isValid():
                        print(f"WARNING: Invalid feature {fid} in layer {layer.name()}")
                        continue
                    
                    geom = feat.geometry()
                    new_geom = self.update_z(geom, x, y, target_z)
                    layer.changeGeometry(fid, new_geom)
                    
                    corrections.append({
                        'layer': layer.name(),
                        'x': x, 'y': y, 'fid': fid,
                        'z_old': entry['z'], 'z_new': target_z
                    })
                    count += 1
                    layer_corrections[layer_id] += 1
                    layers_affected.add(layer.name())
            
            if idx % 10 == 0:
                self.show_progress(True, f"Correcting vertices... ({idx}/{len(self.nodes_csv)})", idx, len(self.nodes_csv))
                QApplication.processEvents()
        
        # Commit changes to all affected layers
        for layer_id, layer in layers_to_edit.items():
            layer.commitChanges()
            layer.updateExtents()
            self.correct_results.append(f"✓ Layer '{layer.name()}': {layer_corrections[layer_id]} corrections\n")
        
        # Store in history
        self.correction_history.append({
            'type': 'internal',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'corrections': corrections,
            'count': count
        })
        
        self.correct_results.append("\n" + "=" * 70 + "\n")
        self.correct_results.append(f"TOTAL CORRECTIONS: {count}\n")
        self.correct_results.append(f"Nodes corrected: {len(self.nodes_csv)}\n")
        self.correct_results.append(f"Layers affected: {len(layers_affected)}\n")
        self.correct_results.append("=" * 70 + "\n\n")
        
        self.correct_results.append("CORRECTION LOGIC (SMART Z SELECTION):\n")
        self.correct_results.append("  - Default: Z = MINIMUM value at each node\n")
        self.correct_results.append("  - Smart rule: If Z_MIN = 0, use Z_MAX instead\n")
        self.correct_results.append("    (Z=0 often indicates missing/error data)\n")
        self.correct_results.append("  - Applied across ALL layers\n")
        self.correct_results.append("  - Ensures internal consistency\n\n")
        
        if nodes_used_max > 0:
            self.correct_results.append(f"SMART RULE APPLIED:\n")
            self.correct_results.append(f"  {nodes_used_max} node(s) had Z_MIN=0\n")
            self.correct_results.append(f"  Used Z_MAX instead for these nodes\n\n")
        
        # Show sample corrections
        if corrections:
            self.correct_results.append("Sample corrections (first 15):\n")
            self.correct_results.append("-" * 70 + "\n")
            for i, c in enumerate(corrections[:15], 1):
                self.correct_results.append(
                    f"{i:2d}. [{c['layer']}] ({c['x']:.2f}, {c['y']:.2f}) FID={c['fid']}: "
                    f"{c['z_old']:.3f} → {c['z_new']:.3f}\n"
                )
        
        # Update summary
        self.update_correction_summary()
        
        self.show_progress(False)
        self.update_status(f"✓ Applied {count} corrections across {len(layers_affected)} layers", "success")
        
        # Enable verify buttons
        self.quick_verify_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)
        
        # Refresh map
        self.iface.mapCanvas().refresh()
        
        QMessageBox.information(self, "Corrections Complete", 
            f"Applied {count} internal corrections\n\n"
            f"Layers affected: {len(layers_affected)}\n"
            f"Nodes corrected: {len(self.nodes_csv)}\n\n"
            f"Correction rule: Z = MINIMUM at each node\n\n"
            "Use 'Quick Verify' to check results")
    
    
    def apply_external(self):
        """
        Apply EXTERNAL corrections - handles intersections BETWEEN different shapefiles.
        
        Logic:
        1. Find where lines from different shapefiles INTERSECT
        2. At each intersection point (X, Y):
           - Determine Z from both lines
           - Lower Z value prevails
           - If vertex exists: change Z to lower value
           - If no vertex: INSERT vertex with lower Z value
        """
        layers = self.get_selected_layers()
        if not layers or len(layers) < 2:
            QMessageBox.warning(self, "Need Multiple Layers", 
                "External corrections require 2+ layers.\n\n"
                "Select multiple shapefiles to check intersections between them.")
            return
        
        self.correct_results.clear()
        self.correct_results.append("=" * 70 + "\n")
        self.correct_results.append("EXTERNAL NODES CORRECTION\n")
        self.correct_results.append("INTERSECTIONS BETWEEN DIFFERENT SHAPEFILES\n")
        self.correct_results.append("=" * 70 + "\n\n")
        
        self.correct_results.append(f"Checking intersections between {len(layers)} shapefiles:\n")
        for i, layer in enumerate(layers, 1):
            self.correct_results.append(f"  {i}. {layer.name()}\n")
        self.correct_results.append("\nRule: At intersections, Z = LOWER value\n")
        self.correct_results.append("Action: Insert vertex if needed, set Z to minimum\n\n")
        
        self.update_status("Finding intersections between layers...", "processing")
        
        # Count total comparisons for progress
        total_comparisons = sum(1 for i in range(len(layers)) for _ in layers[i+1:])
        self.show_progress(True, "Analyzing intersections...", 0, total_comparisons)
        
        all_intersections = []
        comparison_count = 0
        
        # Check each pair of layers
        for i, layer1 in enumerate(layers):
            for layer2 in layers[i+1:]:
                self.correct_results.append(f"Checking: {layer1.name()} ↔ {layer2.name()}\n")
                
                intersections = self.find_layer_intersections(layer1, layer2)
                all_intersections.extend(intersections)
                
                self.correct_results.append(f"  Found {len(intersections)} intersection(s)\n")
                
                comparison_count += 1
                self.show_progress(True, f"Analyzing intersections... ({comparison_count}/{total_comparisons})", 
                                 comparison_count, total_comparisons)
                QApplication.processEvents()
        
        if not all_intersections:
            self.correct_results.append("\n✓ No intersections found between layers\n")
            self.show_progress(False)
            self.update_status("✓ No external corrections needed", "success")
            QMessageBox.information(self, "No Intersections", 
                "No intersection points found between the selected shapefiles.")
            return
        
        self.correct_results.append(f"\n{'='*70}\n")
        self.correct_results.append(f"TOTAL INTERSECTIONS: {len(all_intersections)}\n")
        self.correct_results.append(f"{'='*70}\n\n")
        
        # Apply corrections
        self.correct_results.append("Applying corrections...\n\n")
        self.show_progress(True, "Applying external corrections...", 0, len(all_intersections))
        
        corrections_made = 0
        vertices_inserted = 0
        layers_to_commit = set()
        smart_rule_used = 0  # Track when MAX was used instead of MIN
        
        for idx, intersection in enumerate(all_intersections):
            layer1_id = intersection['layer1_id']
            layer2_id = intersection['layer2_id']
            fid1 = intersection['fid1']
            fid2 = intersection['fid2']
            x, y = intersection['x'], intersection['y']
            z1, z2 = intersection['z1'], intersection['z2']
            
            # SMART Z SELECTION: If minimum is 0, use maximum instead
            z_min = min(z1, z2)
            z_max = max(z1, z2)
            
            if z_min == 0.0 and z_max != 0.0:
                target_z = z_max
                smart_rule_used += 1
            else:
                target_z = z_min
            
            # Get layer objects
            layer1 = QgsProject.instance().mapLayer(layer1_id)
            layer2 = QgsProject.instance().mapLayer(layer2_id)
            
            if not layer1 or not layer2:
                continue
            
            # Start editing if not already
            if not layer1.isEditable():
                layer1.startEditing()
                layers_to_commit.add(layer1)
            if not layer2.isEditable():
                layer2.startEditing()
                layers_to_commit.add(layer2)
            
            # Process layer 1
            feat1 = layer1.getFeature(fid1)
            if feat1.isValid():
                geom1 = feat1.geometry()
                
                # Check if vertex exists
                has_vertex1 = self.has_vertex_at(geom1, x, y)
                
                if has_vertex1:
                    # Vertex exists - update Z if needed
                    if z1 != target_z:
                        new_geom1 = self.update_z(geom1, x, y, target_z)
                        layer1.changeGeometry(fid1, new_geom1)
                        corrections_made += 1
                        self.correct_results.append(
                            f"  [{layer1.name()}] ({x:.2f}, {y:.2f}): {z1:.3f} → {target_z:.3f}\n"
                        )
                else:
                    # No vertex - insert one
                    new_geom1 = self.insert_vertex_at_exact_point(geom1, x, y, target_z, tolerance=0)
                    if new_geom1:
                        layer1.changeGeometry(fid1, new_geom1)
                        vertices_inserted += 1
                        corrections_made += 1
                        self.correct_results.append(
                            f"  [{layer1.name()}] ({x:.2f}, {y:.2f}): INSERTED vertex Z={target_z:.3f}\n"
                        )
            
            # Process layer 2
            feat2 = layer2.getFeature(fid2)
            if feat2.isValid():
                geom2 = feat2.geometry()
                
                # Check if vertex exists
                has_vertex2 = self.has_vertex_at(geom2, x, y)
                
                if has_vertex2:
                    # Vertex exists - update Z if needed
                    if z2 != target_z:
                        new_geom2 = self.update_z(geom2, x, y, target_z)
                        layer2.changeGeometry(fid2, new_geom2)
                        corrections_made += 1
                        self.correct_results.append(
                            f"  [{layer2.name()}] ({x:.2f}, {y:.2f}): {z2:.3f} → {target_z:.3f}\n"
                        )
                else:
                    # No vertex - insert one
                    new_geom2 = self.insert_vertex_at_exact_point(geom2, x, y, target_z, tolerance=0)
                    if new_geom2:
                        layer2.changeGeometry(fid2, new_geom2)
                        vertices_inserted += 1
                        corrections_made += 1
                        self.correct_results.append(
                            f"  [{layer2.name()}] ({x:.2f}, {y:.2f}): INSERTED vertex Z={target_z:.3f}\n"
                        )
            
            if idx % 10 == 0:
                self.show_progress(True, f"Applying corrections... ({idx}/{len(all_intersections)})", 
                                 idx, len(all_intersections))
                QApplication.processEvents()
        
        # Commit all changes
        for layer in layers_to_commit:
            layer.commitChanges()
            layer.updateExtents()
        
        # Store in history
        self.correction_history.append({
            'type': 'external',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'corrections': all_intersections,
            'count': corrections_made
        })
        
        self.correct_results.append(f"\n{'='*70}\n")
        self.correct_results.append("CORRECTION SUMMARY\n")
        self.correct_results.append(f"{'='*70}\n")
        self.correct_results.append(f"Total corrections: {corrections_made}\n")
        self.correct_results.append(f"Vertices inserted: {vertices_inserted}\n")
        self.correct_results.append(f"Vertices updated: {corrections_made - vertices_inserted}\n")
        self.correct_results.append(f"Layers affected: {len(layers_to_commit)}\n\n")
        
        self.correct_results.append("CORRECTION LOGIC (SMART Z SELECTION):\n")
        self.correct_results.append("  - Default: Z = LOWER value at intersection\n")
        self.correct_results.append("  - Smart rule: If Z_MIN = 0, use Z_MAX instead\n")
        self.correct_results.append("    (Z=0 often indicates missing/error data)\n\n")
        
        if smart_rule_used > 0:
            self.correct_results.append(f"SMART RULE APPLIED:\n")
            self.correct_results.append(f"  {smart_rule_used} intersection(s) had Z_MIN=0\n")
            self.correct_results.append(f"  Used Z_MAX instead for these intersections\n\n")
        
        self.update_correction_summary()
        self.show_progress(False)
        self.update_status(f"✓ Applied {corrections_made} external corrections", "success")
        
        # Enable verify
        self.quick_verify_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)
        
        # Refresh map
        self.iface.mapCanvas().refresh()
        
        QMessageBox.information(self, "External Corrections Complete",
            f"Applied {corrections_made} corrections at intersection points\n\n"
            f"Vertices inserted: {vertices_inserted}\n"
            f"Vertices updated: {corrections_made - vertices_inserted}\n\n"
            f"Correction logic:\n"
            f"• Default: Z = LOWER value\n"
            f"• If Z_MIN = 0: Z = HIGHER value\n"
            + (f"\n{smart_rule_used} intersection(s) used smart rule (Z_MIN was 0)" if smart_rule_used > 0 else ""))
    
    def find_layer_intersections(self, layer1, layer2):
        """
        Find intersection points between two layers.
        Returns list of intersections with Z values from both lines.
        """
        intersections = []
        tolerance = 0  # Exact matching
        
        for feat1 in layer1.getFeatures():
            geom1 = feat1.geometry()
            if geom1.isEmpty():
                continue
            
            for feat2 in layer2.getFeatures():
                geom2 = feat2.geometry()
                if geom2.isEmpty():
                    continue
                
                # Check if geometries intersect
                if geom1.intersects(geom2):
                    intersection_geom = geom1.intersection(geom2)
                    
                    if intersection_geom.isEmpty():
                        continue
                    
                    # Extract intersection points
                    points = []
                    if intersection_geom.isMultipart():
                        if intersection_geom.type() == 0:  # Point type
                            points = intersection_geom.asMultiPoint()
                    else:
                        if intersection_geom.type() == 0:  # Point type
                            points = [intersection_geom.asPoint()]
                    
                    # Process each intersection point
                    for pt in points:
                        x, y = pt.x(), pt.y()
                        
                        # Get Z values from both lines at this point
                        z1 = self.get_z_at_exact_point_on_line(geom1, x, y, tolerance)
                        z2 = self.get_z_at_exact_point_on_line(geom2, x, y, tolerance)
                        
                        if z1 is not None and z2 is not None:
                            intersections.append({
                                'layer1_id': layer1.id(),
                                'layer2_id': layer2.id(),
                                'layer1_name': layer1.name(),
                                'layer2_name': layer2.name(),
                                'fid1': feat1.id(),
                                'fid2': feat2.id(),
                                'x': x,
                                'y': y,
                                'z1': z1,
                                'z2': z2
                            })
        
        return intersections
    
    def has_vertex_at(self, geom, x, y):
        """Check if a vertex exists at exact XY coordinates"""
        coords = self.parse_wkt(geom.asWkt())
        for vx, vy, vz in coords:
            if vx == x and vy == y:
                return True
        return False
    def detect_contour_issues(self):
        """Detect contour mismatches without applying corrections"""
        layers = self.get_selected_layers()
        if not layers:
            QMessageBox.warning(self, "No Layer", "Select at least one layer")
            return
        
        if not self.paths['contour']:
            QMessageBox.warning(self, "No Contour", "Select contour file first (Step 2)")
            return
        
        self.contour_results.clear()
        self.contour_results.append("=" * 70 + "\n")
        self.contour_results.append("CONTOUR MISMATCH DETECTION\n")
        self.contour_results.append("=" * 70 + "\n\n")
        
        self.update_status("Detecting contour mismatches...", "processing")
        
        contour = QgsVectorLayer(self.paths['contour'], "contour", "ogr")
        if not contour.isValid():
            QMessageBox.critical(self, "Error", "Cannot load contour file")
            self.update_status("✗ Failed to load contour file", "error")
            return
        
        self.contour_results.append(f"Contour file: {os.path.basename(self.paths['contour'])}\n")
        self.contour_results.append(f"Contour features: {contour.featureCount()}\n\n")
        
        all_issues = []
        total_features = sum(layer.featureCount() for layer in layers)
        processed = 0
        
        self.show_progress(True, "Checking contour intersections...", 0, total_features)
        
        for layer in layers:
            layer_name = layer.name()
            self.contour_results.append(f"\nChecking layer: {layer_name}\n")
            self.contour_results.append("-" * 70 + "\n")
            
            layer_issues = []
            
            for feat in layer.getFeatures():
                geom = feat.geometry()
                for cfeat in contour.getFeatures():
                    cgeom = cfeat.geometry()
                    if geom.intersects(cgeom):
                        inter = geom.intersection(cgeom)
                        pts = [inter.asPoint()] if not inter.isMultipart() else inter.asMultiPoint()
                        for pt in pts:
                            z_line = self.get_z(geom, pt.x(), pt.y())
                            z_cont = self.get_z(cgeom, pt.x(), pt.y())
                            if z_line and z_cont and abs(z_line - z_cont) > 1e-10:
                                layer_issues.append({
                                    'layer': layer_name,
                                    'fid': feat.id(),
                                    'x': pt.x(), 'y': pt.y(),
                                    'z_old': z_line,
                                    'z_contour': z_cont,
                                    'diff': abs(z_line - z_cont)
                                })
                
                processed += 1
                if processed % 50 == 0:
                    self.show_progress(True, f"Checking contour intersections... ({processed}/{total_features})", processed, total_features)
                    QApplication.processEvents()
            
            if layer_issues:
                self.contour_results.append(f"  Found {len(layer_issues)} mismatches\n")
                
                # Show statistics
                max_diff = max(issue['diff'] for issue in layer_issues)
                avg_diff = sum(issue['diff'] for issue in layer_issues) / len(layer_issues)
                self.contour_results.append(f"  Max difference: {max_diff:.3f}\n")
                self.contour_results.append(f"  Avg difference: {avg_diff:.3f}\n")
                
                # Show samples
                self.contour_results.append("\n  Sample mismatches (first 5):\n")
                for i, issue in enumerate(layer_issues[:5], 1):
                    self.contour_results.append(
                        f"  {i}. FID={issue['fid']}: ({issue['x']:.2f}, {issue['y']:.2f}) "
                        f"Z={issue['z_old']:.3f} → Contour={issue['z_contour']:.3f} "
                        f"(Δ={issue['diff']:.3f})\n"
                    )
                
                all_issues.extend(layer_issues)
            else:
                self.contour_results.append("  ✓ No mismatches found\n")
        
        self.show_progress(False)
        
        # Summary
        self.contour_results.append("\n" + "=" * 70 + "\n")
        self.contour_results.append("DETECTION SUMMARY\n")
        self.contour_results.append("=" * 70 + "\n")
        self.contour_results.append(f"Total layers checked: {len(layers)}\n")
        self.contour_results.append(f"Total mismatches found: {len(all_issues)}\n")
        
        if all_issues:
            self.contour_results.append(f"\n⚠ {len(all_issues)} mismatches detected\n")
            self.contour_results.append("→ Proceed to Step 4 to apply corrections\n")
            self.correct_contour_btn.setEnabled(True)
            self.update_status(f"✓ Found {len(all_issues)} contour mismatches", "warning")
        else:
            self.contour_results.append("\n✓ No mismatches found - data already aligned with contours\n")
            self.correct_contour_btn.setEnabled(False)
            self.update_status("✓ No contour mismatches found", "success")
        
        # Store for later use
        self.detected_contour_issues = all_issues
    
    def apply_contour(self):
        """Apply contour corrections (Z = CONTOUR) with progress"""
        layers = self.get_selected_layers()
        if not layers:
            QMessageBox.warning(self, "No Layer", "Select at least one layer")
            return
        
        if not self.paths['contour']:
            QMessageBox.warning(self, "No Contour", "Select contour file first (Step 2)")
            return
        
        self.contour_results.append("\n" + "=" * 70 + "\n")
        self.contour_results.append("APPLYING CONTOUR CORRECTIONS (Z = CONTOUR)\n")
        self.contour_results.append("=" * 70 + "\n\n")
        
        self.update_status("Applying contour corrections...", "processing")
        
        contour = QgsVectorLayer(self.paths['contour'], "contour", "ogr")
        if not contour.isValid():
            QMessageBox.critical(self, "Error", "Cannot load contour file")
            return
        
        all_corrections = []
        total_features = sum(layer.featureCount() for layer in layers)
        processed = 0
        
        self.show_progress(True, "Applying contour corrections...", 0, total_features)
        
        for layer in layers:
            layer_name = layer.name()
            self.contour_results.append(f"\nProcessing layer: {layer_name}\n")
            self.contour_results.append("-" * 70 + "\n")
            
            issues = []
            
            # Find issues
            for feat in layer.getFeatures():
                geom = feat.geometry()
                for cfeat in contour.getFeatures():
                    cgeom = cfeat.geometry()
                    if geom.intersects(cgeom):
                        inter = geom.intersection(cgeom)
                        pts = [inter.asPoint()] if not inter.isMultipart() else inter.asMultiPoint()
                        for pt in pts:
                            z_line = self.get_z(geom, pt.x(), pt.y())
                            z_cont = self.get_z(cgeom, pt.x(), pt.y())
                            if z_line and z_cont and abs(z_line - z_cont) > 1e-10:
                                issues.append({
                                    'layer': layer_name,
                                    'fid': feat.id(),
                                    'x': pt.x(), 'y': pt.y(),
                                    'z_old': z_line,
                                    'z_contour': z_cont
                                })
                
                processed += 1
                if processed % 50 == 0:
                    self.show_progress(True, f"Checking intersections... ({processed}/{total_features})", processed, total_features)
                    QApplication.processEvents()
            
            if not issues:
                self.contour_results.append("  ✓ No corrections needed\n")
                continue
            
            # Apply corrections
            self.contour_results.append(f"  Correcting {len(issues)} mismatches...\n")
            
            layer.startEditing()
            for idx, issue in enumerate(issues):
                feat = layer.getFeature(issue['fid'])
                geom = feat.geometry()
                new_geom = self.update_z(geom, issue['x'], issue['y'], issue['z_contour'])
                layer.changeGeometry(issue['fid'], new_geom)
            
            layer.commitChanges()
            
            self.contour_results.append(f"  ✓ Applied {len(issues)} corrections\n")
            
            # Show samples
            if issues:
                self.contour_results.append("\n  Sample corrections (first 5):\n")
                for i, issue in enumerate(issues[:5], 1):
                    self.contour_results.append(
                        f"  {i}. FID={issue['fid']}: ({issue['x']:.2f}, {issue['y']:.2f}) "
                        f"{issue['z_old']:.3f} → {issue['z_contour']:.3f}\n"
                    )
            
            all_corrections.extend(issues)
        
        # Store in history
        if all_corrections:
            self.correction_history.append({
                'type': 'contour',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'corrections': all_corrections,
                'count': len(all_corrections)
            })
        
        self.show_progress(False)
        
        # Summary
        self.contour_results.append("\n" + "=" * 70 + "\n")
        self.contour_results.append("CORRECTION SUMMARY\n")
        self.contour_results.append("=" * 70 + "\n")
        self.contour_results.append(f"Total layers processed: {len(layers)}\n")
        self.contour_results.append(f"Total corrections applied: {len(all_corrections)}\n")
        
        if all_corrections:
            self.contour_results.append(f"\n✓ Successfully corrected {len(all_corrections)} nodes\n")
            self.contour_results.append("→ Go to tab 5 (Verify) to check results\n")
            self.update_status(f"✓ Fixed {len(all_corrections)} contour mismatches", "success")
        else:
            self.contour_results.append("\n✓ No corrections needed\n")
            self.update_status("✓ No contour corrections needed", "success")
        
        self.update_correction_summary()
        self.quick_verify_btn.setEnabled(True)
        self.verify_btn.setEnabled(True)
    
    def quick_verify(self):
        """Quick verification after corrections"""
        layer = self.get_layer()
        if not layer:
            return
        
        self.correct_results.append("\n" + "=" * 70 + "\n")
        self.correct_results.append("QUICK VERIFICATION\n")
        self.correct_results.append("=" * 70 + "\n\n")
        
        self.update_status("Running quick verification...", "processing")
        self.show_progress(True, "Verifying corrections...", 0, 0)
        
        # Check for remaining issues
        nodes = defaultdict(list)
        for feat in layer.getFeatures():
            geom = feat.geometry()
            if not geom.isEmpty():
                coords = self.parse_wkt(geom.asWkt())
                for x, y, z in coords:
                    if abs(z) > 1e-10:
                        nodes[(x, y)].append({'fid': feat.id(), 'z': z})
        
        remaining_issues = []
        for (x, y), entries in nodes.items():
            z_values = [e['z'] for e in entries]
            if len(set(z_values)) > 1:
                remaining_issues.append({
                    'x': x, 'y': y,
                    'z_values': list(set(z_values))
                })
        
        self.show_progress(False)
        
        if remaining_issues:
            self.correct_results.append(f"⚠ {len(remaining_issues)} issues remain\n")
            self.correct_results.append("\nSample remaining issues:\n")
            for issue in remaining_issues[:5]:
                self.correct_results.append(f"  ({issue['x']:.2f}, {issue['y']:.2f}): {issue['z_values']}\n")
            
            self.update_status(f"⚠ {len(remaining_issues)} issues remain - Correct again", "warning")
            self.correct_remaining_btn.setVisible(True)
            self.nodes_csv = [{'x': i['x'], 'y': i['y'], 'entries': nodes[(i['x'], i['y'])], 
                             'z_min': min(i['z_values']), 'z_max': max(i['z_values']),
                             'z_diff': max(i['z_values']) - min(i['z_values'])} 
                            for i in remaining_issues]
        else:
            self.correct_results.append("✓✓ SUCCESS - No issues remain!\n")
            self.correct_results.append("All nodes have consistent Z values\n")
            self.update_status("✓ Quick verify passed - Ready for final verification", "success")
            self.correct_remaining_btn.setVisible(False)
            self.verify_btn.setEnabled(True)
    
    def correct_remaining(self):
        """Apply corrections to remaining issues"""
        self.apply_internal()
    
    def update_correction_summary(self):
        """Update correction summary display"""
        if not self.correction_history:
            return
        
        self.correction_summary.clear()
        self.correction_summary.append("CORRECTION HISTORY:\n")
        self.correction_summary.append("-" * 70 + "\n")
        
        total_corrections = 0
        for entry in self.correction_history:
            self.correction_summary.append(
                f"{entry['timestamp']} - {entry['type'].upper()}: {entry['count']} corrections\n"
            )
            total_corrections += entry['count']
        
        self.correction_summary.append("-" * 70 + "\n")
        self.correction_summary.append(f"TOTAL CORRECTIONS APPLIED: {total_corrections}\n")
    
    # ========== VERIFICATION ==========
    
    def run_verification(self):
        """Run complete final verification"""
        layer = self.get_layer()
        if not layer:
            QMessageBox.warning(self, "No Layer", "Select a layer first")
            return
        
        self.verify_results.clear()
        self.verify_results.append("=" * 70 + "\n")
        self.verify_results.append("FINAL QUALITY VERIFICATION\n")
        self.verify_results.append("=" * 70 + "\n\n")
        
        self.update_status("Running final verification...", "processing")
        self.show_progress(True, "Verifying data quality...", 0, 0)
        
        # Update statistics
        if self.detection_stats:
            self.stats_display.clear()
            self.stats_display.append("BEFORE CORRECTIONS:\n")
            self.stats_display.append(f"  Problem nodes: {self.detection_stats['problem_nodes']}\n")
            self.stats_display.append(f"  Total nodes: {self.detection_stats['total_nodes']}\n\n")
            
            if self.correction_history:
                total_corrections = sum(h['count'] for h in self.correction_history)
                self.stats_display.append("CORRECTIONS APPLIED:\n")
                self.stats_display.append(f"  Total corrections: {total_corrections}\n")
                for h in self.correction_history:
                    self.stats_display.append(f"  {h['type']}: {h['count']}\n")
        
        # CHECK 1: Internal consistency
        self.verify_results.append("CHECK 1: Internal Node Consistency\n")
        self.verify_results.append("-" * 70 + "\n")
        
        nodes = defaultdict(list)
        for feat in layer.getFeatures():
            geom = feat.geometry()
            if not geom.isEmpty():
                coords = self.parse_wkt(geom.asWkt())
                for x, y, z in coords:
                    if abs(z) > 1e-10:
                        nodes[(x, y)].append({'fid': feat.id(), 'z': z})
        
        internal_issues = []
        for (x, y), entries in nodes.items():
            z_values = [e['z'] for e in entries]
            if len(set(z_values)) > 1:
                internal_issues.append({
                    'x': x, 'y': y,
                    'z_values': list(set(z_values))
                })
        
        self.verify_results.append(f"Total nodes: {len(nodes)}\n")
        self.verify_results.append(f"Nodes with Z differences: {len(internal_issues)}\n")
        
        if internal_issues:
            self.verify_results.append("\n✗ FAILED - Issues remain\n")
            self.verify_results.append("\nSample issues:\n")
            for issue in internal_issues[:5]:
                self.verify_results.append(f"  ({issue['x']:.2f}, {issue['y']:.2f}): {issue['z_values']}\n")
        else:
            self.verify_results.append("\n✓ PASSED - All internal nodes match\n")
        
        # CHECK 2: Contour alignment (if available)
        contour_issues = []
        if self.paths['contour']:
            self.verify_results.append("\n" + "-" * 70 + "\n")
            self.verify_results.append("CHECK 2: Contour Alignment\n")
            self.verify_results.append("-" * 70 + "\n")
            
            contour = QgsVectorLayer(self.paths['contour'], "contour", "ogr")
            if contour.isValid():
                for feat in layer.getFeatures():
                    geom = feat.geometry()
                    for cfeat in contour.getFeatures():
                        cgeom = cfeat.geometry()
                        if geom.intersects(cgeom):
                            inter = geom.intersection(cgeom)
                            pts = [inter.asPoint()] if not inter.isMultipart() else inter.asMultiPoint()
                            for pt in pts:
                                z_line = self.get_z(geom, pt.x(), pt.y())
                                z_cont = self.get_z(cgeom, pt.x(), pt.y())
                                if z_line and z_cont and abs(z_line - z_cont) > 1e-10:
                                    contour_issues.append({
                                        'x': pt.x(), 'y': pt.y(),
                                        'z_line': z_line, 'z_contour': z_cont
                                    })
                
                self.verify_results.append(f"Contour intersections with Z differences: {len(contour_issues)}\n")
                
                if contour_issues:
                    self.verify_results.append("\n✗ FAILED - Contour mismatches remain\n")
                    for issue in contour_issues[:5]:
                        self.verify_results.append(
                            f"  ({issue['x']:.2f}, {issue['y']:.2f}): "
                            f"Line={issue['z_line']:.2f}, Contour={issue['z_contour']:.2f}\n"
                        )
                else:
                    self.verify_results.append("\n✓ PASSED - All contour intersections match\n")
        
        # FINAL RESULT
        total_issues = len(internal_issues) + len(contour_issues)
        
        self.verify_results.append("\n" + "=" * 70 + "\n")
        self.verify_results.append("FINAL RESULT\n")
        self.verify_results.append("=" * 70 + "\n")
        
        # Update stats display with after results
        self.stats_display.append("\nAFTER CORRECTIONS:\n")
        self.stats_display.append(f"  Remaining issues: {total_issues}\n")
        self.stats_display.append(f"  Internal differences: {len(internal_issues)}\n")
        if self.paths['contour']:
            self.stats_display.append(f"  Contour differences: {len(contour_issues)}\n")
        
        if total_issues == 0:
            self.verify_results.append("\n✓✓✓ SUCCESS - ALL CHECKS PASSED ✓✓✓\n")
            self.verify_results.append(f"\nInternal differences: 0\n")
            if self.paths['contour']:
                self.verify_results.append(f"Contour differences: 0\n")
            self.verify_results.append(f"\nTOTAL DIFFERENCES: 0\n\n")
            self.verify_results.append("🎉 Your data is ready for export!\n")
            self.verify_results.setStyleSheet("background:#e8f5e9;font-family:monospace")
            self.update_status("✓✓ VERIFICATION PASSED - 0 differences!", "success")
            self.export_btn.setEnabled(True)
            self.export_btn.setStyleSheet("background:#4CAF50;color:white;font-weight:bold;font-size:16px")
        else:
            self.verify_results.append(f"\n✗ FAILED - {total_issues} DIFFERENCES REMAIN\n")
            self.verify_results.append(f"\nInternal differences: {len(internal_issues)}\n")
            if self.paths['contour']:
                self.verify_results.append(f"Contour differences: {len(contour_issues)}\n")
            self.verify_results.append(f"\nTOTAL DIFFERENCES: {total_issues}\n\n")
            self.verify_results.append("⚠ Return to Correction tab and fix remaining issues\n")
            self.verify_results.setStyleSheet("background:#ffebee;font-family:monospace")
            self.update_status(f"✗ VERIFICATION FAILED - {total_issues} differences", "error")
            
            # Switch back to correction tab
            self.tabs.setCurrentIndex(2)
        
        self.show_progress(False)
    
    # ========== EXPORT ==========
    
    def update_crs_display(self):
        """Update the CRS display label"""
        if not hasattr(self, 'crs_display'):
            return
        
        if self.crs_original.isChecked():
            layers = self.get_selected_layers()
            if layers:
                crs = layers[0].crs()
                self.crs_display.setText(f"Will use: {crs.authid()} - {crs.description()}")
            else:
                self.crs_display.setText("Will use: Original layer CRS (no layer selected)")
        else:
            crs = self.crs_selector.crs()
            self.crs_display.setText(f"Will use: {crs.authid()} - {crs.description()}")
    
    def do_export(self):
        """Export ALL corrected layers as separate shapefiles with comprehensive reports"""
        layers = self.get_selected_layers()
        if not layers or not self.paths['output']:
            QMessageBox.warning(self, "Missing", "Need layers and output folder")
            return
        
        self.export_results.clear()
        self.export_results.append("=" * 70 + "\n")
        self.export_results.append("EXPORT FINAL RESULTS - ALL LAYERS\n")
        self.export_results.append("=" * 70 + "\n\n")
        
        self.update_status("Exporting all layers...", "processing")
        self.show_progress(True, "Exporting shapefiles...", 0, len(layers) + 2)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Determine which CRS to use
        if self.crs_original.isChecked():
            use_original_crs = True
            export_crs = None  # Will use each layer's CRS
            self.export_results.append("CRS: Using original layer CRS for each file\n\n")
        else:
            use_original_crs = False
            export_crs = self.crs_selector.crs()
            self.export_results.append(f"CRS: Reprojecting all layers to {export_crs.authid()} - {export_crs.description()}\n\n")
        
        # 1. Export each layer as separate shapefile
        exported_files = []
        for idx, layer in enumerate(layers):
            # Create filename from original layer name
            layer_name = layer.name()
            # Clean filename (remove invalid characters)
            clean_name = "".join(c for c in layer_name if c.isalnum() or c in (' ', '-', '_')).strip()
            clean_name = clean_name.replace(' ', '_')
            
            output_file = os.path.join(self.paths['output'], f"{clean_name}_CORRECTED_{timestamp}.shp")
            
            self.export_results.append(f"Exporting: {layer_name}...\n")
            
            # Determine CRS for this layer
            if use_original_crs:
                target_crs = layer.crs()
                self.export_results.append(f"  CRS: {target_crs.authid()}\n")
            else:
                target_crs = export_crs
                if layer.crs() != target_crs:
                    self.export_results.append(f"  Reprojecting: {layer.crs().authid()} → {target_crs.authid()}\n")
                else:
                    self.export_results.append(f"  CRS: {target_crs.authid()} (no reprojection needed)\n")
            
            error = QgsVectorFileWriter.writeAsVectorFormat(
                layer, output_file, "UTF-8", target_crs, "ESRI Shapefile"
            )
            
            if error[0] != QgsVectorFileWriter.NoError:
                self.export_results.append(f"  ✗ FAILED: {error[1]}\n")
                continue
            
            exported_files.append({
                'layer_name': layer_name,
                'file': output_file,
                'features': layer.featureCount()
            })
            
            self.export_results.append(f"  ✓ Saved: {os.path.basename(output_file)}\n")
            self.export_results.append(f"  Features: {layer.featureCount()}\n\n")
            
            self.show_progress(True, f"Exporting shapefiles... ({idx+1}/{len(layers)})", idx+1, len(layers) + 2)
            QApplication.processEvents()
        
        if not exported_files:
            self.show_progress(False)
            QMessageBox.critical(self, "Error", "No files were exported successfully")
            return
        
        self.show_progress(True, "Generating correction log...", len(layers) + 1, len(layers) + 2)
        
        # 2. Export correction log (CSV)
        base_name = f"CORRECTIONS_{timestamp}"
        csv_file = None
        if self.correction_history:
            csv_file = os.path.join(self.paths['output'], f"{base_name}.csv")
            with open(csv_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Timestamp', 'Type', 'Layer', 'X', 'Y', 'FID', 'Z_Old', 'Z_New'])
                for entry in self.correction_history:
                    correction_type = entry['type']
                    entry_timestamp = entry['timestamp']
                    
                    for corr in entry['corrections']:
                        # Handle different correction formats
                        if correction_type == 'external':
                            # External corrections have fid1/fid2, z1/z2
                            # Write two rows - one for each feature involved
                            writer.writerow([
                                entry_timestamp, correction_type,
                                corr.get('layer1_name', ''),
                                corr['x'], corr['y'], corr.get('fid1', ''),
                                corr.get('z1', ''), min(corr.get('z1', 0), corr.get('z2', 0))
                            ])
                            writer.writerow([
                                entry_timestamp, correction_type,
                                corr.get('layer2_name', ''),
                                corr['x'], corr['y'], corr.get('fid2', ''),
                                corr.get('z2', ''), min(corr.get('z1', 0), corr.get('z2', 0))
                            ])
                        else:
                            # Internal/contour corrections have fid, z_old, z_new
                            writer.writerow([
                                entry_timestamp, correction_type,
                                corr.get('layer', ''),
                                corr['x'], corr['y'], corr.get('fid', ''),
                                corr.get('z_old', ''), 
                                corr.get('z_new', corr.get('z_contour', ''))
                            ])
            self.export_results.append(f"✓ Correction log: {csv_file}\n\n")
        
        self.show_progress(True, "Generating summary report...", len(layers) + 2, len(layers) + 2)
        
        # 3. Export summary report (TXT)
        base_name = f"EXPORT_SUMMARY_{timestamp}"
        txt_file = os.path.join(self.paths['output'], f"{base_name}.txt")
        with open(txt_file, 'w') as f:
            f.write("=" * 70 + "\n")
            f.write("Z-COORDINATE CORRECTION SUMMARY - ALL LAYERS\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # List all exported layers
            f.write("EXPORTED LAYERS:\n")
            f.write("-" * 70 + "\n")
            for exp in exported_files:
                f.write(f"Layer: {exp['layer_name']}\n")
                f.write(f"  File: {os.path.basename(exp['file'])}\n")
                f.write(f"  Features: {exp['features']}\n\n")
            f.write(f"Total layers exported: {len(exported_files)}\n\n")
            
            if self.detection_stats:
                f.write("DETECTION STATISTICS:\n")
                f.write(f"  Total nodes: {self.detection_stats['total_nodes']}\n")
                f.write(f"  Problem nodes found: {self.detection_stats['problem_nodes']}\n")
                f.write(f"  Detection time: {self.detection_stats['detection_time']:.2f}s\n\n")
            
            if self.correction_history:
                f.write("CORRECTIONS APPLIED:\n")
                total = 0
                for entry in self.correction_history:
                    f.write(f"  {entry['timestamp']} - {entry['type'].upper()}: {entry['count']}\n")
                    total += entry['count']
                f.write(f"  TOTAL: {total} corrections\n\n")
            
            f.write("FILES GENERATED:\n")
            f.write("EXPORTED FILES:\n")
            f.write("-" * 70 + "\n")
            for exp in exported_files:
                f.write(f"  • {os.path.basename(exp['file'])}\n")
            if self.correction_history:
                f.write(f"  • {os.path.basename(csv_file)}\n")
            f.write(f"  • {os.path.basename(txt_file)}\n")
        
        self.export_results.append(f"✓ Summary report: {txt_file}\n\n")
        
        self.export_results.append("=" * 70 + "\n")
        self.export_results.append("EXPORT SUMMARY\n")
        self.export_results.append("=" * 70 + "\n")
        self.export_results.append(f"Layers exported: {len(exported_files)}\n")
        total_features = sum(exp['features'] for exp in exported_files)
        self.export_results.append(f"Total features: {total_features}\n")
        
        if self.correction_history:
            total_corrections = sum(h['count'] for h in self.correction_history)
            self.export_results.append(f"Total corrections applied: {total_corrections}\n")
        
        self.export_results.append("\n✓ EXPORT COMPLETE\n")
        
        self.show_progress(False)
        self.update_status(f"✓ Export complete - {len(exported_files)} layers exported", "success")
        
        # Add layers to map if checkbox is checked
        if self.add_to_map_checkbox.isChecked():
            self.export_results.append("\nAdding layers to map...\n")
            self.show_progress(True, "Adding layers to map...", 0, len(exported_files))
            QApplication.processEvents()
            
            added_layers = []
            for idx, exp in enumerate(exported_files):
                layer_path = exp['file']
                layer_name = os.path.splitext(os.path.basename(layer_path))[0]
                
                # Load the shapefile as a vector layer
                vector_layer = QgsVectorLayer(layer_path, layer_name, "ogr")
                
                if vector_layer.isValid():
                    # Add to project
                    QgsProject.instance().addMapLayer(vector_layer)
                    added_layers.append(layer_name)
                    self.export_results.append(f"  ✓ Added: {layer_name}\n")
                else:
                    self.export_results.append(f"  ✗ Failed to add: {layer_name}\n")
                
                self.show_progress(True, f"Adding layers to map... ({idx+1}/{len(exported_files)})", idx+1, len(exported_files))
                QApplication.processEvents()
            
            self.show_progress(False)
            self.export_results.append(f"\n✓ Added {len(added_layers)} layer(s) to map\n")
            self.update_status(f"✓ Export complete - {len(added_layers)} layers added to map", "success")
        
        # Build file list for message
        file_list = "\n".join([f"• {os.path.basename(exp['file'])}" for exp in exported_files])
        
        # Build message based on whether layers were added to map
        message_parts = [
            f"Successfully exported {len(exported_files)} layer(s)!\n\n"
            f"Shapefiles:\n{file_list}\n\n"
            f"Reports:\n"
            f"• {os.path.basename(csv_file) if self.correction_history else 'No corrections to log'}\n"
            f"• {os.path.basename(txt_file)}\n\n"
            f"Location: {self.paths['output']}"
        ]
        
        if self.add_to_map_checkbox.isChecked():
            message_parts.append(f"\n\n✓ {len(exported_files)} layer(s) added to map")
        
        QMessageBox.information(self, "Export Complete", "".join(message_parts))
    
    # ========== HELPERS ==========
    
    def parse_wkt(self, wkt):
        """Extract XYZ from WKT"""
        coords = []
        pattern = r'([-\d.eE]+)\s+([-\d.eE]+)(?:\s+([-\d.eE]+))?'
        for match in re.findall(pattern, wkt):
            coords.append((float(match[0]), float(match[1]), float(match[2] or 0)))
        return coords
    
    def get_z(self, geom, x, y, tol=1e-6):
        """
        Get Z at point.
        First tries exact matching at vertices.
        If not found, interpolates Z along the line segment where the point lies.
        
        tol: tolerance for considering points as "on" a line segment (default 1e-6)
        """
        coords = self.parse_wkt(geom.asWkt())
        
        # First, try exact match with vertices (no tolerance)
        for vx, vy, vz in coords:
            if vx == x and vy == y:
                return vz
        
        # If not an exact vertex match, interpolate along line segments
        for i in range(len(coords) - 1):
            x1, y1, z1 = coords[i]
            x2, y2, z2 = coords[i + 1]
            
            # Check if point (x, y) lies on line segment from (x1,y1) to (x2,y2)
            # Using parametric line equation: P = P1 + t*(P2-P1) where 0 <= t <= 1
            
            dx = x2 - x1
            dy = y2 - y1
            
            # Avoid division by zero
            if abs(dx) < 1e-10 and abs(dy) < 1e-10:
                continue  # Degenerate segment (same point twice)
            
            # Find parameter t
            if abs(dx) > abs(dy):
                # Use x-coordinate to find t
                t = (x - x1) / dx
            else:
                # Use y-coordinate to find t
                t = (y - y1) / dy
            
            # Check if t is within valid range [0, 1]
            if t < -tol or t > 1 + tol:
                continue
            
            # Clamp t to [0, 1]
            t = max(0.0, min(1.0, t))
            
            # Calculate expected point on segment
            px = x1 + t * dx
            py = y1 + t * dy
            
            # Check if this matches our target point within tolerance
            dist = math.sqrt((px - x)**2 + (py - y)**2)
            if dist < tol:
                # Interpolate Z-value
                z = z1 + t * (z2 - z1)
                return z
        
        return None
    
    def update_z(self, geom, x, y, new_z, tol=1e-6):
        """
        Update Z at point.
        If point is an existing vertex: update its Z-value
        If point lies on a segment: insert a new vertex at that point with new_z
        
        tol: tolerance for considering points as "on" a line segment (default 1e-6)
        """
        coords = self.parse_wkt(geom.asWkt())
        new_coords = []
        updated = False
        
        for i, (vx, vy, vz) in enumerate(coords):
            # Check if this is the exact vertex to update
            if vx == x and vy == y:
                new_coords.append((vx, vy, new_z))
                updated = True
            else:
                new_coords.append((vx, vy, vz))
                
                # Check if we need to insert a vertex between this one and the next
                if not updated and i < len(coords) - 1:
                    x1, y1, z1 = vx, vy, vz
                    x2, y2, z2 = coords[i + 1]
                    
                    dx = x2 - x1
                    dy = y2 - y1
                    
                    # Avoid division by zero
                    if abs(dx) < 1e-10 and abs(dy) < 1e-10:
                        continue
                    
                    # Find parameter t
                    if abs(dx) > abs(dy):
                        t = (x - x1) / dx
                    else:
                        t = (y - y1) / dy
                    
                    # Check if t is within valid range [0, 1]
                    if t < -tol or t > 1 + tol:
                        continue
                    
                    # Clamp t to [0, 1]
                    t = max(0.0, min(1.0, t))
                    
                    # Calculate expected point on segment
                    px = x1 + t * dx
                    py = y1 + t * dy
                    
                    # Check if this matches our target point within tolerance
                    dist = math.sqrt((px - x)**2 + (py - y)**2)
                    if dist < tol:
                        # Insert new vertex at intersection point
                        new_coords.append((x, y, new_z))
                        updated = True
        
        if not updated:
            # Debug warning if vertex not found
            print(f"WARNING: update_z could not find vertex or segment for point ({x}, {y})")
            print(f"  Available vertices: {[(c[0], c[1]) for c in coords[:5]]}...")
        
        wkt = geom.asWkt()
        coord_str = ", ".join([f"{c[0]} {c[1]} {c[2]}" for c in new_coords])
        if "MULTI" in wkt.upper():
            new_wkt = f"MULTILINESTRING Z (({coord_str}))"
        else:
            new_wkt = f"LINESTRING Z ({coord_str})"
        
        return QgsGeometry.fromWkt(new_wkt)
    
    def unload(self):
        """Cleanup"""
        if self.action:
            self.iface.removePluginMenu("Z Tools", self.action)
            self.iface.removeToolBarIcon(self.action)
