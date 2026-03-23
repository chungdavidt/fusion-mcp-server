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


def _state_fingerprint():
    """Quick fingerprint of design state: bodies-sketches-timeline."""
    try:
        design, root_comp = _get_design_context()
        b = root_comp.bRepBodies.count
        s = root_comp.sketches.count
        t = design.timeline.markerPosition
        return f"{b}-{s}-{t}"
    except Exception:
        return "unknown"


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

    # Store original tool decorator, wrap it to append state fingerprint
    _orig_tool = fusion_mcp.tool

    def _tracked_tool(*args, **kwargs):
        """Decorator that registers a tool AND appends state fingerprint to its output."""
        import functools
        decorator = _orig_tool(*args, **kwargs)
        def wrapper(func):
            @functools.wraps(func)
            def with_fp(*a, **kw):
                result = func(*a, **kw)
                return f"{result} [state:{_state_fingerprint()}]"
            return decorator(with_fp)
        return wrapper

    tool = _tracked_tool  # use this instead of @fusion_mcp.tool()

    # ------------------------------------------------------------------
    # Sketch creation (moved from MCPServerCommand.py)
    # ------------------------------------------------------------------

    @tool()
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

    @tool()
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

    @tool()
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

    @tool()
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

    @tool()
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

    @tool()
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

    @tool()
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

    @tool()
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

    @tool()
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

    @tool()
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

    @tool()
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

    @tool()
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

    @tool()
    def get_body_info(body_index: int = -1) -> str:
        """Get edge and face information for a body. Use this before fillet/chamfer/shell
        to find the right indices. body_index: -1 = last body."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            edges_info = []
            for i in range(body.edges.count):
                edge = body.edges.item(i)
                entry = {"index": i, "length_cm": round(edge.length, 4)}
                sv = edge.startVertex
                ev = edge.endVertex
                if sv and ev:
                    entry["start"] = {"x": round(sv.geometry.x, 4), "y": round(sv.geometry.y, 4), "z": round(sv.geometry.z, 4)}
                    entry["end"] = {"x": round(ev.geometry.x, 4), "y": round(ev.geometry.y, 4), "z": round(ev.geometry.z, 4)}
                edges_info.append(entry)

            faces_info = []
            for i in range(body.faces.count):
                face = body.faces.item(i)
                entry = {"index": i, "area_cm2": round(face.area, 4)}
                try:
                    centroid = face.centroid
                    entry["centroid"] = {"x": round(centroid.x, 4), "y": round(centroid.y, 4), "z": round(centroid.z, 4)}
                    _, normal = face.evaluator.getNormalAtPoint(centroid)
                    entry["normal"] = {"x": round(normal.x, 4), "y": round(normal.y, 4), "z": round(normal.z, 4)}
                except Exception:
                    pass
                faces_info.append(entry)

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

    @tool()
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

    @tool()
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

    @tool()
    def undo(count: int = 1) -> str:
        """Undo the last operation(s) in the design by rolling back the timeline."""
        try:
            design, _ = _get_design_context()
            timeline = design.timeline
            if timeline.count == 0:
                return "Nothing to undo — timeline is empty"
            current = timeline.markerPosition
            steps = min(count, current)
            if steps == 0:
                return "Already at the beginning of the timeline"
            timeline.markerPosition = current - steps
            return f"Rolled back {steps} operation(s) — timeline at position {current - steps}/{timeline.count}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error undoing: {str(e)}"

    @tool()
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

    @tool()
    def delete_sketch(sketch_index: int = -1) -> str:
        """Delete a sketch from the design. sketch_index: -1 = last sketch.
        WARNING: Cannot delete sketches that have dependent features (e.g. extrudes)."""
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
            if not sketch.deleteMe():
                return (
                    f"Cannot delete sketch '{sketch_name}' — it may have "
                    f"dependent features. Delete those features first or use undo."
                )
            return f"Deleted sketch: {sketch_name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error deleting sketch: {str(e)}"

    # ------------------------------------------------------------------
    # Export — Phase 3
    # ------------------------------------------------------------------

    @tool()
    def export_stl(filepath: str, body_index: int = -1) -> str:
        """Export a body to STL format (for 3D printing).
        filepath: output file path (e.g. '~/Desktop/part.stl').
        body_index: which body to export (-1 = last). Use list_bodies to find indices."""
        try:
            import os
            design, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            filepath = os.path.expanduser(filepath)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)

            export_mgr = design.exportManager
            stl_options = export_mgr.createSTLExportOptions(body, filepath)
            stl_options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementMedium
            export_mgr.execute(stl_options)
            return f"Exported '{body.name}' as STL to: {filepath}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error exporting STL: {str(e)}"

    @tool()
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
    # Phase A: Boolean Operations + List Bodies
    # ------------------------------------------------------------------

    @tool()
    def list_bodies() -> str:
        """List all bodies in the design with names, indices, and bounding boxes."""
        try:
            _, root_comp = _get_design_context()
            bodies = []
            for i in range(root_comp.bRepBodies.count):
                body = root_comp.bRepBodies.item(i)
                bb = body.boundingBox
                bodies.append({
                    "index": i,
                    "name": body.name,
                    "bounding_box": {
                        "min": {"x": round(bb.minPoint.x, 4), "y": round(bb.minPoint.y, 4), "z": round(bb.minPoint.z, 4)},
                        "max": {"x": round(bb.maxPoint.x, 4), "y": round(bb.maxPoint.y, 4), "z": round(bb.maxPoint.z, 4)},
                    },
                })
            return json.dumps({"body_count": len(bodies), "bodies": bodies}, indent=2)
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error listing bodies: {str(e)}"

    @tool()
    def combine(target_body_index: int, tool_body_indices: str, operation: str = "cut", keep_tools: bool = False) -> str:
        """Boolean operation on bodies: cut (subtract), join (merge), or intersect.
        target_body_index: body to modify. tool_body_indices: comma-separated indices of tool bodies.
        operation: 'cut', 'join', or 'intersect'. keep_tools: keep tool bodies after operation.
        Use list_bodies to find indices. All dimensions in cm."""
        try:
            _, root_comp = _get_design_context()
            target = _get_body(root_comp, target_body_index)

            indices = [int(i.strip()) for i in tool_body_indices.split(",")]
            tool_bodies = adsk.core.ObjectCollection.create()
            for idx in indices:
                if idx == target_body_index:
                    return f"Tool body index {idx} cannot be the same as target"
                tool_bodies.add(_get_body(root_comp, idx))

            op_map = {
                "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
                "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
                "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
            }
            op_enum = op_map.get(operation.lower())
            if op_enum is None:
                return f"Unknown operation: '{operation}'. Use 'cut', 'join', or 'intersect'."

            combine_features = root_comp.features.combineFeatures
            combine_input = combine_features.createInput(target, tool_bodies)
            combine_input.operation = op_enum
            combine_input.isKeepToolBodies = keep_tools
            feature = combine_features.add(combine_input)
            return f"Combined ({operation}) — feature: {feature.name}, remaining bodies: {root_comp.bRepBodies.count}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error combining: {str(e)}"

    # ------------------------------------------------------------------
    # Phase B: Sketch on Face + Offset Planes
    # ------------------------------------------------------------------

    @tool()
    def create_offset_plane(plane: str, offset: float) -> str:
        """Create a construction plane offset from a standard plane.
        plane: 'XY', 'XZ', or 'YZ'. offset: distance in cm.
        Use the returned name with create_new_sketch."""
        try:
            _, root_comp = _get_design_context()
            plane_map = {
                "XY": root_comp.xYConstructionPlane,
                "XZ": root_comp.xZConstructionPlane,
                "YZ": root_comp.yZConstructionPlane,
            }
            base_plane = plane_map.get(plane.upper())
            if not base_plane:
                return f"Unknown plane: {plane}. Use 'XY', 'XZ', or 'YZ'."

            planes = root_comp.constructionPlanes
            plane_input = planes.createInput()
            plane_input.setByOffset(base_plane, adsk.core.ValueInput.createByReal(offset))
            new_plane = planes.add(plane_input)
            new_plane.name = f"Offset_{plane}_{offset}cm"
            return f"Construction plane created: '{new_plane.name}'. Use create_new_sketch('{new_plane.name}') to sketch on it."
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error creating offset plane: {str(e)}"

    @tool()
    def create_sketch_on_face(body_index: int, face_index: int) -> str:
        """Create a new sketch on a face of an existing body.
        Use get_body_info to find face indices by centroid/normal.
        Face must be planar (flat). Sketch coordinates are in the face's local 2D system."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, body_index)

            if face_index < 0 or face_index >= body.faces.count:
                return f"face_index {face_index} out of range (0-{body.faces.count - 1})"
            face = body.faces.item(face_index)

            sketch = root_comp.sketches.add(face)
            sketch.name = f"FaceSketch_MCP_{int(time.time()) % 10000}"
            origin = sketch.origin
            return (
                f"Sketch created on face {face_index}: {sketch.name}. "
                f"Origin at ({round(origin.x, 4)}, {round(origin.y, 4)}, {round(origin.z, 4)}) cm."
            )
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error creating sketch on face: {str(e)}"

    # ------------------------------------------------------------------
    # Phase C: Body Movement & Interference (works in Part Design mode)
    # ------------------------------------------------------------------

    @tool()
    def move_body(x: float = 0.0, y: float = 0.0, z: float = 0.0,
                  body_index: int = -1) -> str:
        """Move a body by an offset (translation).
        x, y, z: offset in cm. body_index: -1 = last body."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            bodies = adsk.core.ObjectCollection.create()
            bodies.add(body)

            transform = adsk.core.Matrix3D.create()
            transform.translation = adsk.core.Vector3D.create(x, y, z)

            move_feats = root_comp.features.moveFeatures
            move_input = move_feats.createInput2(bodies)
            move_input.defineAsFreeMove(transform)
            feature = move_feats.add(move_input)

            return f"Moved '{body.name}' by ({x}, {y}, {z}) cm — feature: {feature.name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error moving body: {str(e)}"

    @tool()
    def rotate_body(angle: float, axis: str = "Z", body_index: int = -1,
                    origin_x: float = 0.0, origin_y: float = 0.0, origin_z: float = 0.0) -> str:
        """Rotate a body around an axis.
        angle: degrees. axis: 'X', 'Y', or 'Z'. body_index: -1 = last body.
        origin_x/y/z: rotation center in cm (default = world origin)."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            axis_map = {
                "X": adsk.core.Vector3D.create(1, 0, 0),
                "Y": adsk.core.Vector3D.create(0, 1, 0),
                "Z": adsk.core.Vector3D.create(0, 0, 1),
            }
            axis_vec = axis_map.get(axis.upper())
            if not axis_vec:
                return f"Unknown axis: {axis}. Use 'X', 'Y', or 'Z'."

            bodies = adsk.core.ObjectCollection.create()
            bodies.add(body)

            transform = adsk.core.Matrix3D.create()
            origin = adsk.core.Point3D.create(origin_x, origin_y, origin_z)
            transform.setToRotation(math.radians(angle), axis_vec, origin)

            move_feats = root_comp.features.moveFeatures
            move_input = move_feats.createInput2(bodies)
            move_input.defineAsFreeMove(transform)
            feature = move_feats.add(move_input)

            return f"Rotated '{body.name}' by {angle}° around {axis} — feature: {feature.name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error rotating body: {str(e)}"

    @tool()
    def check_interference() -> str:
        """Check for bounding box collisions between all bodies.
        Returns pairs of bodies whose bounding boxes overlap with overlap volume."""
        try:
            _, root_comp = _get_design_context()
            count = root_comp.bRepBodies.count
            if count < 2:
                return "Need at least 2 bodies to check interference"

            boxes = []
            for i in range(count):
                body = root_comp.bRepBodies.item(i)
                bb = body.boundingBox
                if bb:
                    boxes.append((i, body.name, bb))

            collisions = []
            for a in range(len(boxes)):
                for b in range(a + 1, len(boxes)):
                    idx_a, name_a, bb_a = boxes[a]
                    idx_b, name_b, bb_b = boxes[b]
                    if (bb_a.minPoint.x <= bb_b.maxPoint.x and bb_a.maxPoint.x >= bb_b.minPoint.x and
                        bb_a.minPoint.y <= bb_b.maxPoint.y and bb_a.maxPoint.y >= bb_b.minPoint.y and
                        bb_a.minPoint.z <= bb_b.maxPoint.z and bb_a.maxPoint.z >= bb_b.minPoint.z):
                        ox = max(0, min(bb_a.maxPoint.x, bb_b.maxPoint.x) - max(bb_a.minPoint.x, bb_b.minPoint.x))
                        oy = max(0, min(bb_a.maxPoint.y, bb_b.maxPoint.y) - max(bb_a.minPoint.y, bb_b.minPoint.y))
                        oz = max(0, min(bb_a.maxPoint.z, bb_b.maxPoint.z) - max(bb_a.minPoint.z, bb_b.minPoint.z))
                        collisions.append({
                            "body_a": {"index": idx_a, "name": name_a},
                            "body_b": {"index": idx_b, "name": name_b},
                            "overlap_volume_cm3": round(ox * oy * oz, 6),
                        })

            result = {
                "bodies_checked": count,
                "collisions_found": len(collisions),
                "status": f"WARNING: {len(collisions)} collision(s)" if collisions else "No interference detected",
                "collisions": collisions,
            }
            return json.dumps(result, indent=2)
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error checking interference: {str(e)}"

    # ------------------------------------------------------------------
    # Phase D: Patterns & Mirror
    # ------------------------------------------------------------------

    @tool()
    def pattern_rectangular(x_count: int, x_spacing: float,
                            y_count: int = 1, y_spacing: float = 0.0,
                            body_index: int = -1) -> str:
        """Create a rectangular (grid) pattern of a body.
        x_count/y_count: instances including original. x_spacing/y_spacing in cm.
        body_index: -1 = last body."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            bodies = adsk.core.ObjectCollection.create()
            bodies.add(body)

            rect_patterns = root_comp.features.rectangularPatternFeatures
            pattern_input = rect_patterns.createInput(
                bodies, root_comp.xConstructionAxis,
                adsk.core.ValueInput.createByReal(x_count),
                adsk.core.ValueInput.createByReal(x_spacing),
                adsk.fusion.PatternDistanceType.SpacingPatternDistanceType
            )

            if y_count > 1:
                pattern_input.directionTwoEntity = root_comp.yConstructionAxis
                pattern_input.quantityTwo = adsk.core.ValueInput.createByReal(y_count)
                pattern_input.distanceTwo = adsk.core.ValueInput.createByReal(y_spacing)

            feature = rect_patterns.add(pattern_input)
            return f"Rectangular pattern: {x_count}x{y_count} = {x_count * y_count} instances — feature: {feature.name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error creating rectangular pattern: {str(e)}"

    @tool()
    def pattern_circular(count: int, angle: float = 360.0, axis: str = "Z",
                         body_index: int = -1) -> str:
        """Create a circular (radial) pattern of a body.
        count: total instances including original. angle: total span in degrees.
        axis: 'X', 'Y', or 'Z'. body_index: -1 = last body."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            axis_map = {
                "X": root_comp.xConstructionAxis,
                "Y": root_comp.yConstructionAxis,
                "Z": root_comp.zConstructionAxis,
            }
            pattern_axis = axis_map.get(axis.upper())
            if not pattern_axis:
                return f"Unknown axis: {axis}. Use 'X', 'Y', or 'Z'."

            bodies = adsk.core.ObjectCollection.create()
            bodies.add(body)

            circ_patterns = root_comp.features.circularPatternFeatures
            pattern_input = circ_patterns.createInput(bodies, pattern_axis)
            pattern_input.quantity = adsk.core.ValueInput.createByReal(count)
            pattern_input.totalAngle = adsk.core.ValueInput.createByReal(math.radians(angle))
            pattern_input.isSymmetric = False

            feature = circ_patterns.add(pattern_input)
            return f"Circular pattern: {count} instances over {angle}° around {axis} — feature: {feature.name}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error creating circular pattern: {str(e)}"

    @tool()
    def mirror(plane: str = "YZ", body_index: int = -1) -> str:
        """Mirror a body across a construction plane.
        plane: 'XY', 'XZ', or 'YZ'. body_index: -1 = last body."""
        try:
            _, root_comp = _get_design_context()
            body = _get_body(root_comp, None if body_index == -1 else body_index)

            plane_map = {
                "XY": root_comp.xYConstructionPlane,
                "XZ": root_comp.xZConstructionPlane,
                "YZ": root_comp.yZConstructionPlane,
            }
            mirror_plane = plane_map.get(plane.upper())
            if not mirror_plane:
                return f"Unknown plane: {plane}. Use 'XY', 'XZ', or 'YZ'."

            bodies = adsk.core.ObjectCollection.create()
            bodies.add(body)

            mirror_features = root_comp.features.mirrorFeatures
            mirror_input = mirror_features.createInput(bodies, mirror_plane)
            feature = mirror_features.add(mirror_input)
            return f"Mirrored across {plane} — feature: {feature.name}, total bodies: {root_comp.bRepBodies.count}"
        except ValueError as e:
            return str(e)
        except Exception as e:
            return f"Error mirroring: {str(e)}"

    # ------------------------------------------------------------------
    # View
    # ------------------------------------------------------------------

    @tool()
    def fit_view() -> str:
        """Frame all geometry in the viewport."""
        try:
            app = adsk.core.Application.get()
            app.activeViewport.fit()
            return "View fitted to all geometry"
        except Exception as e:
            return f"Error fitting view: {str(e)}"
