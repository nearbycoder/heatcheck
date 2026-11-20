"""Print a summary of a .glb (stdlib only): python3 Tools/web/glbjson.py file.glb"""
import json, struct, sys

def load(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, ver, length = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, "not a glb"
    clen, ctype = struct.unpack_from("<II", data, 12)
    return json.loads(data[20:20 + clen]), data

if __name__ == "__main__":
    g, _ = load(sys.argv[1])
    print("nodes", len(g.get("nodes", [])), "meshes", len(g.get("meshes", [])), "skins", len(g.get("skins", [])))
    for s in g.get("skins", []):
        print(" skin joints", len(s["joints"]), "skeleton", s.get("skeleton"))
    for i, n in enumerate(g.get("nodes", [])):
        print(" node", i, n.get("name"), {k: v for k, v in n.items() if k in ("translation", "rotation", "scale", "mesh", "skin", "children")})
    print("materials", [m.get("name") for m in g.get("materials", [])])
    for a in g.get("animations", []):
        acc = g["accessors"][a["samplers"][0]["input"]]
        print(" anim", a["name"], "channels", len(a["channels"]), "dur", acc.get("max"))
    for m in g.get("meshes", []):
        print(" mesh", m.get("name"), [(sorted(p["attributes"].keys()), g["materials"][p["material"]]["name"] if "material" in p else None) for p in m["primitives"]][:3])
