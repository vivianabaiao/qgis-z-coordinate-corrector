"""
QGIS Z-Coordinate Corrector - Enhanced Version
Plugin initialization file

This file is required by QGIS to load the plugin.
"""

def classFactory(iface):
    """Load the plugin class from z_coordinate_corrector_enhanced module.
    
    Args:
        iface: A QGIS interface instance.
        
    Returns:
        The plugin class instance.
    """
    from .z_coordinate_corrector_enhanced import ZCoordinatePlugin
    return ZCoordinatePlugin(iface)
