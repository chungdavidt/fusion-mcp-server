"""
Fusion 360 MCP Tools — Phase 1: Core Modeling

All tools registered via register_tools(fusion_mcp).
Units: centimeters for distances, degrees for angles.
"""

import adsk.core
import adsk.fusion
import json
import math
import time
import traceback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_design_context():
    """Return (design, root_comp) or raise ValueError."""
    app = adsk.core.Application.get()
    doc = app.activeDocument
    if not doc:
        raise ValueError("No active document")
    design = adsk.fusion.Design.cast(
        doc.products.itemByProductType('DesignProductType')
    )
    if not design:
        raise ValueError("No active design document")
    return design, design.rootComponent


def _get_active_sketch():
    """Return the most recent sketch for drawing operations."""
    _, root_comp = _get_design_context()
    if root_comp.sketches.count == 0:
        raise ValueError("No sketches in design. Call create_new_sketch first.")
    return root_comp.sketches.item(root_comp.sketches.count - 1)


def _get_body(root_comp, body_index=None):
    """Return a BRepBody by index (default: last body) or raise ValueError."""
    count = root_comp.bRepBodies.count
    if count == 0:
        raise ValueError("No bodies in design")
    if body_index is None:
        body_index = count - 1
    if body_index < 0 or body_index >= count:
        raise ValueError(f"body_index {body_index} out of range (0-{count - 1})")
    return root_comp.bRepBodies.item(body_index)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(fusion_mcp):
    """Register all MCP tools on the given FastMCP instance."""

    # ------------------------------------------------------------------
    # Sketch creation (moved from MCPServerCommand.py)
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def create_new_sketch(plane_name: str) -> str:
        """Create a new sketch on the specified plane (XY, XZ, or YZ).
        Also accepts custom construction plane names."""
        try:
            design, root_comp = _get_design_context()

            sketch_plane = None
            name_upper = plane_name.upper()
            if name_upper == "XY":
                sketch_plane = root_comp.xYConstructionPlane
            elif name_upper == "YZ":
                sketch_plane = root_comp.yZConstructionPlane
            elif name_upper == "XZ":
                sketch_plane = root_comp.xZConstructionPlane
            else:
                for i in range(root_comp.constructionPlanes.count):
                    plane = root_comp.constructionPlanes.item(i)
                    if plane.name == plane_name:
                        sketch_plane = plane
                        break

            if not sketch_plane:
                return f"Could not find plane: {plane_name}"

            sketch = root_comp.sketches.add(sketch_plane)
            sketch.name = f"Sketch_MCP_{int(time.time()) % 10000}"
            return f"Sketch created successfully: {sketch.name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error creating sketch: {str(e)}"

    # ------------------------------------------------------------------
    # Parameters (moved from MCPServerCommand.py)
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def create_parameter(name: str, expression: str, unit: str, comment: str = "") -> str:
        """Create a new user parameter in the active design.
        If a parameter with the same name exists, it will be updated."""
        try:
            design, _ = _get_design_context()
            try:
                param = design.userParameters.add(
                    name,
                    adsk.core.ValueInput.createByString(expression),
                    unit, comment
                )
                return f"Parameter created successfully: {param.name} = {param.expression}"
            except Exception:
                existing = design.userParameters.itemByName(name)
                if existing:
                    existing.expression = expression
                    existing.unit = unit
                    if comment:
                        existing.comment = comment
                    return f"Parameter updated: {existing.name} = {existing.expression}"
                raise
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error creating parameter: {str(e)}"

    # ------------------------------------------------------------------
    # Sketch drawing — Phase 1
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def draw_rectangle(x1: float, y1: float, x2: float, y2: float) -> str:
        """Draw a rectangle in the active sketch defined by two opposite corners.
        All dimensions in cm (1 mm = 0.1 cm)."""
        try:
            sketch = _get_active_sketch()
            p1 = adsk.core.Point3D.create(x1, y1, 0)
            p2 = adsk.core.Point3D.create(x2, y2, 0)
            sketch.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)
            return f"Rectangle drawn from ({x1}, {y1}) to ({x2}, {y2}) cm"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error drawing rectangle: {str(e)}"

    @fusion_mcp.tool()
    def draw_circle(center_x: float, center_y: float, radius: float) -> str:
        """Draw a circle in the active sketch.
        All dimensions in cm (1 mm = 0.1 cm)."""
        try:
            sketch = _get_active_sketch()
            center = adsk.core.Point3D.create(center_x, center_y, 0)
            sketch.sketchCurves.sketchCircles.addByCenterRadius(center, radius)
            return f"Circle drawn at ({center_x}, {center_y}) with radius {radius} cm"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error drawing circle: {str(e)}"

    @fusion_mcp.tool()
    def draw_line(x1: float, y1: float, x2: float, y2: float) -> str:
        """Draw a straight line in the active sketch.
        All dimensions in cm (1 mm = 0.1 cm)."""
        try:
            sketch = _get_active_sketch()
            p1 = adsk.core.Point3D.create(x1, y1, 0)
            p2 = adsk.core.Point3D.create(x2, y2, 0)
            sketch.sketchCurves.sketchLines.addByTwoPoints(p1, p2)
            return f"Line drawn from ({x1}, {y1}) to ({x2}, {y2}) cm"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error drawing line: {str(e)}"

    # ------------------------------------------------------------------
    # Sketch management
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def finish_sketch() -> str:
        """Exit sketch editing mode. Must be called after drawing and before extrude."""
        try:
            design, root_comp = _get_design_context()
            # Try to exit sketch edit mode by setting active edit to root component
            try:
                design.activeEditObject = root_comp
            except Exception:
                pass
            return "Sketch editing finished"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error finishing sketch: {str(e)}"

    # ------------------------------------------------------------------
    # 3D operations — Phase 1
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def extrude(distance: float, profile_index: int = 0) -> str:
        """Extrude the most recent sketch profile into a 3D body.
        Distance in cm (positive = forward, negative = backward).
        profile_index selects which profile if the sketch has multiple
        (e.g., a rectangle with a circle cutout creates 2 profiles)."""
        try:
            design, root_comp = _get_design_context()
            sketches = root_comp.sketches
            if sketches.count == 0:
                return "No sketches in design"

            sketch = sketches.item(sketches.count - 1)
            if sketch.profiles.count == 0:
                return "No profiles in sketch. Did you call finish_sketch first?"

            if profile_index < 0 or profile_index >= sketch.profiles.count:
                return (
                    f"profile_index {profile_index} out of range. "
                    f"Sketch has {sketch.profiles.count} profile(s) (0-{sketch.profiles.count - 1})."
                )

            profile = sketch.profiles.item(profile_index)
            extrudes = root_comp.features.extrudeFeatures
            ext_input = extrudes.createInput(
                profile,
                adsk.fusion.FeatureOperations.NewBodyFeatureOperation
            )
            ext_input.setDistanceExtent(
                False,
                adsk.core.ValueInput.createByReal(distance)
            )
            feature = extrudes.add(ext_input)
            return f"Extruded {distance} cm — feature: {feature.name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error extruding: {str(e)}"

    # ------------------------------------------------------------------
    # Inspection — Phase 1
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def get_design_info() -> str:
        """Get information about the active design: name, body count,
        sketch count, and component count."""
        try:
            design, root_comp = _get_design_context()
            info = {
                "design_name": design.parentDocument.name,
                "body_count": root_comp.bRepBodies.count,
                "sketch_count": root_comp.sketches.count,
                "component_count": root_comp.occurrences.count,
                "design_type": "Parametric" if design.designType == adsk.fusion.DesignTypes.ParametricDesignType else "Direct",
            }
            return json.dumps(info, indent=2)
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error getting design info: {str(e)}"

    # ------------------------------------------------------------------
    # 3D operations — Phase 2
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def revolve(angle: float, axis: str = "Y", profile_index: int = 0) -> str:
        """Revolve the most recent sketch profile around an axis to create a 3D body.
        angle: rotation in degrees (360 = full revolution).
        axis: construction axis to revolve around — 'X', 'Y', or 'Z'.
        All dimensions in cm (1 mm = 0.1 cm)."""
        try:
            design, root_comp = _get_design_context()
            sketches = root_comp.sketches
            if sketches.count == 0:
                return "No sketches in design"

            sketch = sketches.item(sketches.count - 1)
            if sketch.profiles.count == 0:
                return "No profiles in sketch. Did you call finish_sketch first?"

            if profile_index < 0 or profile_index >= sketch.profiles.count:
                return (
                    f"profile_index {profile_index} out of range. "
                    f"Sketch has {sketch.profiles.count} profile(s)."
                )

            profile = sketch.profiles.item(profile_index)

            axis_map = {
                "X": root_comp.xConstructionAxis,
                "Y": root_comp.yConstructionAxis,
                "Z": root_comp.zConstructionAxis,
            }
            rev_axis = axis_map.get(axis.upper())
            if not rev_axis:
                return f"Unknown axis: {axis}. Use 'X', 'Y', or 'Z'."

            revolves = root_comp.features.revolveFeatures
            rev_input = revolves.createInput(
                profile, rev_axis,
                adsk.fusion.FeatureOperations.NewBodyFeatureOperation
            )
            rev_input.setAngleExtent(
                False,
                adsk.core.ValueInput.createByReal(math.radians(angle))
            )
            feature = revolves.add(rev_input)
            return f"Revolved {angle}° around {axis} axis — feature: {feature.name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error revolving: {str(e)}"

    # ------------------------------------------------------------------
    # Edge/face modifications — Phase 2
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def fillet(radius: float, edge_indices: str = "", body_index: int = -1) -> str:
        """Round (fillet) edges on a body.
        radius: fillet radius in cm.
        edge_indices: comma-separated edge indices (e.g. '0,1,3'). Empty = all edges.
        body_index: which body (-1 = last body). Use get_body_info to find indices."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            edges = adsk.core.ObjectCollection.create()
            if edge_indices.strip():
                indices = [int(i.strip()) for i in edge_indices.split(",")]
                for idx in indices:
                    if idx < 0 or idx >= body.edges.count:
                        return f"Edge index {idx} out of range (0-{body.edges.count - 1})"
                    edges.add(body.edges.item(idx))
            else:
                for edge in body.edges:
                    edges.add(edge)

            fillets = root_comp.features.filletFeatures
            fillet_input = fillets.createInput()
            fillet_input.addConstantRadiusEdgeSet(
                edges,
                adsk.core.ValueInput.createByReal(radius),
                True
            )
            feature = fillets.add(fillet_input)
            return f"Fillet applied (radius {radius} cm) — feature: {feature.name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error applying fillet: {str(e)}"

    @fusion_mcp.tool()
    def chamfer(distance: float, edge_indices: str = "", body_index: int = -1) -> str:
        """Bevel (chamfer) edges on a body.
        distance: chamfer distance in cm.
        edge_indices: comma-separated edge indices (e.g. '0,1,3'). Empty = all edges.
        body_index: which body (-1 = last body). Use get_body_info to find indices."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            edges = adsk.core.ObjectCollection.create()
            if edge_indices.strip():
                indices = [int(i.strip()) for i in edge_indices.split(",")]
                for idx in indices:
                    if idx < 0 or idx >= body.edges.count:
                        return f"Edge index {idx} out of range (0-{body.edges.count - 1})"
                    edges.add(body.edges.item(idx))
            else:
                for edge in body.edges:
                    edges.add(edge)

            chamfers = root_comp.features.chamferFeatures
            chamfer_input = chamfers.createInput2()
            chamfer_input.chamferEdgeSets.addEqualDistanceChamferEdgeSet(
                edges,
                adsk.core.ValueInput.createByReal(distance),
                True
            )
            feature = chamfers.add(chamfer_input)
            return f"Chamfer applied (distance {distance} cm) — feature: {feature.name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error applying chamfer: {str(e)}"

    @fusion_mcp.tool()
    def shell(thickness: float, face_indices: str = "", body_index: int = -1) -> str:
        """Hollow out a body, leaving walls of the given thickness.
        thickness: wall thickness in cm.
        face_indices: comma-separated face indices to remove (open shell). Empty = closed shell.
        body_index: which body (-1 = last body). Use get_body_info to find indices."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            faces = adsk.core.ObjectCollection.create()
            if face_indices.strip():
                indices = [int(i.strip()) for i in face_indices.split(",")]
                for idx in indices:
                    if idx < 0 or idx >= body.faces.count:
                        return f"Face index {idx} out of range (0-{body.faces.count - 1})"
                    faces.add(body.faces.item(idx))

            shells = root_comp.features.shellFeatures
            shell_input = shells.createInput(faces)
            shell_input.insideThickness = adsk.core.ValueInput.createByReal(thickness)
            feature = shells.add(shell_input)
            return f"Shell applied (thickness {thickness} cm) — feature: {feature.name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error applying shell: {str(e)}"

    # ------------------------------------------------------------------
    # Inspection — Phase 2
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def get_body_info(body_index: int = -1) -> str:
        """Get edge and face information for a body. Use this before fillet/chamfer/shell
        to find the right indices. body_index: -1 = last body."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            edges_info = []
            for i in range(body.edges.count):
                edge = body.edges.item(i)
                edges_info.append({
                    "index": i,
                    "length_cm": round(edge.length, 4),
                })

            faces_info = []
            for i in range(body.faces.count):
                face = body.faces.item(i)
                faces_info.append({
                    "index": i,
                    "area_cm2": round(face.area, 4),
                })

            info = {
                "body_name": body.name,
                "edge_count": body.edges.count,
                "face_count": body.faces.count,
                "edges": edges_info,
                "faces": faces_info,
            }
            return json.dumps(info, indent=2)
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error getting body info: {str(e)}"

    @fusion_mcp.tool()
    def measure(body_index: int = -1) -> str:
        """Measure a body: volume, surface area, and bounding box dimensions.
        body_index: -1 = last body."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            phys = body.physicalProperties
            bb = body.boundingBox
            info = {
                "body_name": body.name,
                "volume_cm3": round(phys.volume, 6),
                "area_cm2": round(phys.area, 4),
                "bounding_box": {
                    "min": {"x": round(bb.minPoint.x, 4), "y": round(bb.minPoint.y, 4), "z": round(bb.minPoint.z, 4)},
                    "max": {"x": round(bb.maxPoint.x, 4), "y": round(bb.maxPoint.y, 4), "z": round(bb.maxPoint.z, 4)},
                    "size": {
                        "x": round(bb.maxPoint.x - bb.minPoint.x, 4),
                        "y": round(bb.maxPoint.y - bb.minPoint.y, 4),
                        "z": round(bb.maxPoint.z - bb.minPoint.z, 4),
                    }
                }
            }
            return json.dumps(info, indent=2)
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error measuring: {str(e)}"

    # ------------------------------------------------------------------
    # Sketch drawing — Phase 3
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def draw_arc(center_x: float, center_y: float,
                 start_x: float, start_y: float,
                 end_x: float, end_y: float) -> str:
        """Draw an arc in the active sketch (counter-clockwise from start to end).
        All dimensions in cm (1 mm = 0.1 cm)."""
        try:
            sketch = _get_active_sketch()
            center = adsk.core.Point3D.create(center_x, center_y, 0)
            start = adsk.core.Point3D.create(start_x, start_y, 0)
            end = adsk.core.Point3D.create(end_x, end_y, 0)
            sketch.sketchCurves.sketchArcs.addByCenterStartEnd(center, start, end)
            return f"Arc drawn — center ({center_x}, {center_y}), start ({start_x}, {start_y}), end ({end_x}, {end_y}) cm"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error drawing arc: {str(e)}"

    # ------------------------------------------------------------------
    # Utility — Phase 3
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def undo(count: int = 1) -> str:
        """Undo the last operation(s) in the design."""
        try:
            app = adsk.core.Application.get()
            for i in range(count):
                app.executeTextCommand('Commands.Undo')
            return f"Undid {count} operation(s)"
        except Exception as e:
            return f"Error undoing: {str(e)}"

    @fusion_mcp.tool()
    def delete_body(body_index: int = -1) -> str:
        """Delete a body from the design. body_index: -1 = last body."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)
            body_name = body.name
            root_comp.features.removeFeatures.add(body)
            return f"Deleted body: {body_name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error deleting body: {str(e)}"

    @fusion_mcp.tool()
    def delete_sketch(sketch_index: int = -1) -> str:
        """Delete a sketch from the design. sketch_index: -1 = last sketch."""
        try:
            _, root_comp = _get_design_context()
            count = root_comp.sketches.count
            if count == 0:
                return "No sketches to delete"
            if sketch_index == -1:
                sketch_index = count - 1
            if sketch_index < 0 or sketch_index >= count:
                return f"sketch_index {sketch_index} out of range (0-{count - 1})"
            sketch = root_comp.sketches.item(sketch_index)
            sketch_name = sketch.name
            sketch.deleteMe()
            return f"Deleted sketch: {sketch_name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error deleting sketch: {str(e)}"

    # ------------------------------------------------------------------
    # Export — Phase 3
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def export_stl(filepath: str) -> str:
        """Export the design to STL format (for 3D printing).
        filepath: output file path (e.g. '~/Desktop/part.stl')."""
        try:
            import os
            design, root_comp = _get_design_context()
            if root_comp.bRepBodies.count == 0:
                return "No bodies to export"

            filepath = os.path.expanduser(filepath)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            export_mgr = design.exportManager
            body = root_comp.bRepBodies.item(0)
            stl_options = export_mgr.createSTLExportOptions(body, filepath)
            stl_options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
            export_mgr.execute(stl_options)
            return f"Exported STL to: {filepath}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error exporting STL: {str(e)}"

    @fusion_mcp.tool()
    def export_step(filepath: str) -> str:
        """Export the design to STEP format (CAD standard interchange).
        filepath: output file path (e.g. '~/Desktop/part.step')."""
        try:
            import os
            design, root_comp = _get_design_context()

            filepath = os.path.expanduser(filepath)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            export_mgr = design.exportManager
            step_options = export_mgr.createSTEPExportOptions(filepath, root_comp)
            export_mgr.execute(step_options)
            return f"Exported STEP to: {filepath}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error exporting STEP: {str(e)}"

    # ------------------------------------------------------------------
    # View
    # ------------------------------------------------------------------

    @fusion_mcp.tool()
    def fit_view() -> str:
        """Frame all geometry in the viewport."""
        try:
            app = adsk.core.Application.get()
            app.activeViewport.fit()
            return "View fitted to all geometry"
        except Exception as e:
            return f"Error fitting view: {str(e)}"
