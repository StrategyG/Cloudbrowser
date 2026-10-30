extends Node3D
# Intentional MVP: fixed camera and procedural root motion. No IK/foot lock guarantee.
var actor: Node3D
var skeleton: Skeleton3D
var cfg: Dictionary = {}
var frame_index := 0
var origin: Vector3

func _ready() -> void:
    var f := FileAccess.open("res://manifest.json", FileAccess.READ)
    if f == null:
        push_error("manifest.json not found")
        get_tree().quit(2)
        return
    var parsed = JSON.parse_string(f.get_as_text())
    if typeof(parsed) != TYPE_DICTIONARY:
        push_error("Malformed manifest")
        get_tree().quit(2)
        return
    cfg = parsed
    var packed := load("res://actor.glb") as PackedScene
    if packed == null:
        push_error("Rigged GLB import failed")
        get_tree().quit(2)
        return
    actor = packed.instantiate() as Node3D
    if actor == null:
        push_error("Root GLB is not Node3D")
        get_tree().quit(2)
        return
    add_child(actor)
    origin = actor.position
    skeleton = _find_skeleton(actor)
    if skeleton == null:
        push_error("No Skeleton3D in imported GLB")
        get_tree().quit(2)
        return
    var floor_mesh := PlaneMesh.new()
    floor_mesh.size = Vector2(200,200)
    var floor_instance := MeshInstance3D.new()
    floor_instance.mesh = floor_mesh
    add_child(floor_instance)
    floor_instance.position.y = -0.02
    var mat := StandardMaterial3D.new()
    mat.albedo_color = Color(0.18,0.24,0.31)
    floor_instance.material_override = mat
    var light := DirectionalLight3D.new()
    light.rotation_degrees = Vector3(-45,-35,0)
    add_child(light)
    var camera := Camera3D.new()
    camera.position = Vector3(0,1.35,5)
    add_child(camera)
    camera.look_at(Vector3(0,1,0),Vector3.UP)
    camera.current = true

func _find_skeleton(n: Node) -> Skeleton3D:
    if n is Skeleton3D: return n as Skeleton3D
    for child in n.get_children():
        var s := _find_skeleton(child)
        if s != null: return s
    return null

func _process(_delta: float) -> void:
    if actor == null or skeleton == null: return
    var fps: float = float(cfg.get("fps",24))
    var sec: float = float(frame_index) / fps
    var action: String = str(cfg.get("action","idle"))
    frame_index += 1
    actor.position = origin
    if action == "walk":
        actor.position.x += min(sec, float(cfg.get("duration",5))) * 0.25
    elif action == "jump":
        actor.position.y += abs(sin(sec*3.14159265)) * 0.35
    # Explicitly restore poses to avoid additive drift between recorded frames.
    for i in skeleton.get_bone_count():
        skeleton.set_bone_pose_rotation(i, Quaternion.IDENTITY)
    if action == "wave" or action == "walk":
        for i in skeleton.get_bone_count():
            var name := skeleton.get_bone_name(i).to_lower()
            if (action == "wave" and ("hand" in name or "forearm" in name)) or (action == "walk" and "leg" in name):
                skeleton.set_bone_pose_rotation(i,Quaternion(Vector3.RIGHT,sin(sec*6.28318)*0.17))
