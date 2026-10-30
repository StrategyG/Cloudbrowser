extends Node3D
## Offline single-actor scene runner. Input manifest MUST be human approved.
## Godot 4.7: import GLB once using --headless --editor --import, then capture
## deterministic output via --write-movie + --fixed-fps + --quit-after N.

var manifest: Dictionary = {}
var actor: Node3D
var skeleton: Skeleton3D
var camera: Camera3D
var env_node: WorldEnvironment
var light: DirectionalLight3D
var shot_lookup: Array[Dictionary] = []
var original_rotations: Dictionary = {}
var ground_offset: float = 0.0
var traveled: float = 0.0
var last_shot: int = -1
var frame_index: int = 0

func fatal(message: String) -> void:
    push_error("STUDIO_GODOT_ERROR: " + message)
    get_tree().quit(2)

func _ready() -> void:
    var path: String = "res://manifest.json"
    if not FileAccess.file_exists(path):
        fatal("Missing manifest.json")
        return
    var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path))
    if typeof(parsed) != TYPE_DICTIONARY:
        fatal("Manifest JSON is not an object")
        return
    manifest = parsed as Dictionary
    if manifest.get("approval", "") != "approved":
        fatal("Manifest was not approved")
        return
    var fps: int = int(manifest.get("fps", 0))
    if fps not in [24, 30, 60]:
        fatal("Unsupported frame rate")
        return
    if not manifest.has("shots") or typeof(manifest["shots"]) != TYPE_ARRAY:
        fatal("No shots")
        return
    var cursor: int = 0
    for shot_value in manifest["shots"]:
        if typeof(shot_value) != TYPE_DICTIONARY:
            fatal("Invalid shot")
            return
        var shot: Dictionary = shot_value
        if str(shot.get("action", "")) not in ["idle", "walk", "wave", "jump"]:
            fatal("Unsupported action")
            return
        var count: int = roundi(float(shot.get("duration", 0)) * fps)
        if count < 1:
            fatal("Invalid shot duration")
            return
        shot_lookup.append({"start": cursor, "end": cursor + count, "shot": shot})
        cursor += count
    if cursor <= 0 or cursor > 900:
        fatal("Frame limit exceeded")
        return

    var packed: Resource = load("res://assets/character.glb")
    if not (packed is PackedScene):
        fatal("Rigged GLB failed to import as PackedScene")
        return
    var instance: Node = (packed as PackedScene).instantiate()
    if not (instance is Node3D):
        fatal("GLB scene root is not Node3D")
        return
    actor = instance as Node3D
    add_child(actor)
    var rigs: Array[Skeleton3D] = []
    collect_rigs(actor, rigs)
    if rigs.size() != 1:
        fatal("Expected exactly one Skeleton3D, found %d" % rigs.size())
        return
    skeleton = rigs[0]
    if skeleton.get_bone_count() <= 0:
        fatal("Skeleton has no bones")
        return
    skeleton.reset_bone_poses()
    for i in range(skeleton.get_bone_count()):
        original_rotations[i] = skeleton.get_bone_pose_rotation(i)
    var floor_y: float = minimum_actor_y(actor)
    if not is_finite(floor_y):
        fatal("No renderable mesh found")
        return
    ground_offset = -floor_y
    actor.position.y = ground_offset
    setup_camera()
    setup_environment()
    configure_shot(shot_lookup[0]["shot"])
    set_process(true)

func collect_rigs(node: Node, rigs: Array[Skeleton3D]) -> void:
    if node is Skeleton3D:
        rigs.append(node as Skeleton3D)
    for child in node.get_children():
        collect_rigs(child, rigs)

func minimum_actor_y(node: Node) -> float:
    var min_y: float = INF
    if node is MeshInstance3D:
        var mesh_node: MeshInstance3D = node as MeshInstance3D
        if mesh_node.mesh != null:
            var box: AABB = mesh_node.mesh.get_aabb()
            for i in range(8):
                min_y = minf(min_y, (mesh_node.global_transform * box.get_endpoint(i)).y)
    for child in node.get_children():
        min_y = minf(min_y, minimum_actor_y(child))
    return min_y

func setup_camera() -> void:
    camera = Camera3D.new()
    camera.name = "OfflineCamera"
    camera.projection = Camera3D.PROJECTION_ORTHOGONAL
    camera.size = 3.6
    camera.current = true
    add_child(camera)

func setup_environment() -> void:
    env_node = WorldEnvironment.new()
    env_node.name = "WorldEnvironment"
    var environment := Environment.new()
    environment.background_mode = Environment.BG_COLOR
    environment.background_color = Color(0.09, 0.12, 0.19)
    environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
    environment.ambient_light_color = Color(0.5, 0.55, 0.68)
    environment.ambient_light_energy = 0.75
    env_node.environment = environment
    add_child(env_node)
    light = DirectionalLight3D.new()
    light.name = "MainLight"
    light.rotation_degrees = Vector3(-55, 35, 0)
    light.light_energy = 1.5
    add_child(light)

func material_for(color: Color) -> StandardMaterial3D:
    var material := StandardMaterial3D.new()
    material.albedo_color = color
    material.roughness = 0.9
    return material

func box_mesh(name: String, pos: Vector3, size: Vector3, color: Color, parent: Node3D) -> void:
    var box := BoxMesh.new()
    box.size = size
    var node := MeshInstance3D.new()
    node.name = name
    node.mesh = box
    node.material_override = material_for(color)
    node.position = pos
    parent.add_child(node)

func configure_shot(shot: Dictionary) -> void:
    var prior: Node = get_node_or_null("EnvironmentGeometry")
    if prior:
        remove_child(prior)
        prior.free()
    var stage := Node3D.new()
    stage.name = "EnvironmentGeometry"
    add_child(stage)
    var location: String = str(shot.get("location", "studio"))
    var lighting: String = str(shot.get("lighting", "neutral"))
    var floor := PlaneMesh.new()
    floor.size = Vector2(200, 200)
    var floor_object := MeshInstance3D.new()
    floor_object.name = "GroundPlane_Y0"
    floor_object.mesh = floor
    floor_object.material_override = material_for(Color(0.18, 0.21, 0.26))
    stage.add_child(floor_object)
    var background: Color = Color(0.09, 0.12, 0.19)
    light.light_color = Color.WHITE
    light.light_energy = 1.5
    if lighting == "sunset" or lighting == "warm":
        background = Color(0.25, 0.12, 0.13)
        light.light_color = Color(1.0, 0.73, 0.54)
    elif lighting == "night":
        background = Color(0.015, 0.025, 0.08)
        light.light_color = Color(0.48, 0.62, 1.0)
        light.light_energy = 0.75
    env_node.environment.background_color = background
    if location == "arusia":
        var generator := RandomNumberGenerator.new()
        generator.seed = 19
        for side in [-1, 1]:
            for i in range(6):
                var height: float = 1.0 + generator.randf_range(0.2, 2.3)
                box_mesh("ARUSIA_Street_Building_%d_%d" % [side, i],
                    Vector3(float(side) * (3.5 + i * 0.72), height / 2.0, -2.8 - i * 0.15),
                    Vector3(0.75, height, 0.8), Color(0.25, 0.28 + 0.03 * i, 0.45), stage)
    elif location == "forest":
        var generator := RandomNumberGenerator.new()
        generator.seed = 7
        for i in range(14):
            var trunk := CylinderMesh.new()
            trunk.top_radius = 0.08
            trunk.bottom_radius = 0.1
            trunk.height = 1.2
            var trunk_node := MeshInstance3D.new()
            trunk_node.name = "TreeTrunk_%d" % i
            trunk_node.mesh = trunk
            trunk_node.position = Vector3((-1 if i % 2 == 0 else 1) * (2.5 + i * 0.25), 0.6, -2.7 - generator.randf())
            trunk_node.material_override = material_for(Color(0.32, 0.22, 0.16))
            stage.add_child(trunk_node)
            var foliage := SphereMesh.new()
            foliage.radius = 0.65
            foliage.height = 1.35
            var foliage_node := MeshInstance3D.new()
            foliage_node.name = "TreeCrown_%d" % i
            foliage_node.mesh = foliage
            foliage_node.position = trunk_node.position + Vector3(0, 1.4, 0)
            foliage_node.material_override = material_for(Color(0.13, 0.38, 0.20))
            stage.add_child(foliage_node)

func pose_bone(bone_name: String, axis: Vector3, angle: float) -> void:
    var idx: int = skeleton.find_bone(bone_name)
    if idx < 0:
        return
    var base: Quaternion = original_rotations[idx]
    skeleton.set_bone_pose_rotation(idx, base * Quaternion(axis, angle))

func reset_pose() -> void:
    for idx in original_rotations:
        skeleton.set_bone_pose_rotation(int(idx), original_rotations[idx])

func _process(_delta: float) -> void:
    if frame_index >= 900 or shot_lookup.is_empty():
        get_tree().quit(2)
        return
    var segment_index: int = -1
    var segment: Dictionary = {}
    for index in range(shot_lookup.size()):
        var candidate: Dictionary = shot_lookup[index]
        if frame_index >= int(candidate["start"]) and frame_index < int(candidate["end"]):
            segment = candidate
            segment_index = index
            break
    if segment_index < 0:
        get_tree().quit()
        return
    if last_shot != segment_index:
        if last_shot >= 0:
            var previous: Dictionary = shot_lookup[last_shot]["shot"]
            if str(previous.get("action", "")) == "walk":
                traveled += float(shot_lookup[last_shot]["end"] - shot_lookup[last_shot]["start"]) / float(manifest["fps"]) * 0.55
        configure_shot(segment["shot"])
        last_shot = segment_index
    var shot: Dictionary = segment["shot"]
    var local_index: int = frame_index - int(segment["start"])
    var frame_count: int = int(segment["end"]) - int(segment["start"])
    var seconds: float = float(local_index) / float(manifest["fps"])
    var phase: float = seconds * TAU * 1.4
    reset_pose()
    actor.position = Vector3(traveled, ground_offset, 0)
    match str(shot.get("action", "idle")):
        "walk":
            actor.position.x += seconds * 0.55
            actor.position.y += absf(sin(phase)) * 0.014
            pose_bone("UpperLeg_L", Vector3.RIGHT, 0.45 * sin(phase))
            pose_bone("UpperLeg_R", Vector3.RIGHT, -0.45 * sin(phase))
            pose_bone("UpperArm_L", Vector3.RIGHT, -0.32 * sin(phase))
            pose_bone("UpperArm_R", Vector3.RIGHT, 0.32 * sin(phase))
        "wave":
            pose_bone("UpperArm_R", Vector3.FORWARD, -0.9)
            pose_bone("LowerArm_R", Vector3.RIGHT, 0.25 * sin(phase))
        "jump":
            var progress: float = float(local_index) / float(maxi(1, frame_count - 1))
            actor.position.y += 0.45 * maxf(0.0, sin(PI * progress))
        _:
            pose_bone("Chest", Vector3.RIGHT, 0.015 * sin(seconds * TAU))
    var focus := Vector3(actor.position.x, 1.1, 0)
    var camera_type: String = str(shot.get("camera", "static"))
    if camera_type == "orbit":
        var angle: float = TAU * float(local_index) / float(maxi(1, frame_count))
        camera.position = Vector3(actor.position.x + 5.0 * sin(angle), 1.6, 5.0 * cos(angle))
    else:
        camera.position = Vector3(actor.position.x, 1.6, 5.0)
    camera.size = 2.45 if camera_type == "closeup" else 3.6
    camera.look_at(focus, Vector3.UP)
    frame_index += 1
