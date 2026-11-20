// HEAT CHECK web asset post-process (gltf-transform).
//
//   node Tools/web/postprocess.mjs <build_dir> <assets_out_dir>
//
// Reads the raw GLBs written by blender_characters.py / blender_static.py, then:
//   * rewrites every material from Art/Export/Materials/*.json (names kept exactly),
//   * embeds the web-sized textures prepared by build_web_assets.sh (<build_dir>/img),
//   * crowd meshes: keeps the per-fan attribute _FAN (float VEC2 = phase, amplitude), stores
//     COLOR_0 as unorm8 and drops the now-redundant TEXCOORD_0,
//   * characters: drops the unused TEXCOORD_0 and removes redundant animation keys,
//   * compresses the big files (arena, arena_lite, player, referee) with EXT_meshopt_compression
//     (+ KHR_mesh_quantization for normals/uv/colour/weights). POSITION stays float32, so no
//     dequantisation transforms are added to any node: every node keeps its authored TRS.
// Writes <build_dir>/post_stats.json for the manifest step.
import fs from 'node:fs';
import path from 'node:path';
import { Logger, NodeIO, PropertyType, TextureInfo } from '@gltf-transform/core';
import {
	ALL_EXTENSIONS,
	EXTMeshoptCompression,
	KHRMaterialsEmissiveStrength,
	KHRMeshQuantization,
} from '@gltf-transform/extensions';
import { dedup, prune, quantize, reorder, resample } from '@gltf-transform/functions';
import { MeshoptDecoder, MeshoptEncoder } from 'meshoptimizer';

const [BUILD, OUT] = process.argv.slice(2);
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');
const EXPORT = path.join(ROOT, 'Art', 'Export');
const IMG = path.join(BUILD, 'img');
// Unreal multiplies every emissive_strength by HC_EMISSIVE_SCALE (Tools/ue_import.py, default
// 0.35); use the same factor so emissive surfaces have the Unreal balance under tone mapping.
const EMISSIVE_SCALE = 0.35;

const MATS = {};
for (const f of fs.readdirSync(path.join(EXPORT, 'Materials')).filter((f) => f.endsWith('.json'))) {
	Object.assign(MATS, JSON.parse(fs.readFileSync(path.join(EXPORT, 'Materials', f), 'utf8')));
}

// texture name -> embedded web file (prepared by build_web_assets.sh)
const TEXTURES = {
	T_Court: 'T_Court.jpg',
	T_Ball: 'T_Ball.jpg',
	T_Banners: 'T_Banners.png',
	T_JumboScreen: 'T_JumboScreen.jpg',
	T_LedScroll: 'T_LedScroll.jpg',
	T_ShotClock: 'T_ShotClock.png',
};

const JOBS = [
	{ name: 'player', src: 'player_raw.glb', out: 'characters/player.glb', kind: 'character', compress: true },
	{ name: 'referee', src: 'referee_raw.glb', out: 'characters/referee.glb', kind: 'character', compress: true },
	{ name: 'court', src: 'court_raw.glb', out: 'arena/court.glb', kind: 'static', compress: false },
	{ name: 'arena', src: 'arena_raw.glb', out: 'arena/arena.glb', kind: 'static', compress: true },
	{ name: 'arena_lite', src: 'arena_lite_raw.glb', out: 'arena/arena_lite.glb', kind: 'static', compress: true },
	{ name: 'hoop', src: 'hoop_raw.glb', out: 'arena/hoop.glb', kind: 'static', compress: false },
	{ name: 'ball', src: 'ball_raw.glb', out: 'arena/ball.glb', kind: 'static', compress: false },
];

await MeshoptEncoder.ready;
await MeshoptDecoder.ready;
const io = new NodeIO()
	.registerExtensions(ALL_EXTENSIONS)
	.registerDependencies({ 'meshopt.encoder': MeshoptEncoder, 'meshopt.decoder': MeshoptDecoder });

function texture(doc, cache, name) {
	if (cache.has(name)) return cache.get(name);
	const file = TEXTURES[name];
	if (!file) throw new Error(`no web texture mapping for ${name}`);
	const buf = fs.readFileSync(path.join(IMG, file));
	const tex = doc
		.createTexture(name)
		.setImage(new Uint8Array(buf))
		.setMimeType(file.endsWith('.png') ? 'image/png' : 'image/jpeg')
		.setURI(file);
	cache.set(name, tex);
	return tex;
}

function sampler(info) {
	info.setWrapS(TextureInfo.WrapMode.REPEAT)
		.setWrapT(TextureInfo.WrapMode.REPEAT)
		.setMagFilter(TextureInfo.MagFilter.LINEAR)
		.setMinFilter(TextureInfo.MinFilter.LINEAR_MIPMAP_LINEAR);
}

function rewriteMaterials(doc) {
	const emissiveExt = doc.createExtension(KHRMaterialsEmissiveStrength);
	const cache = new Map();
	const report = {};
	for (const mat of doc.getRoot().listMaterials()) {
		const name = mat.getName().replace(/\.\d{3}$/, '');
		mat.setName(name);
		const d = MATS[name];
		if (!d) throw new Error(`material ${name} missing from Art/Export/Materials/*.json`);
		// reset everything Blender wrote
		for (const ext of mat.listExtensions()) mat.setExtension(ext.extensionName, null);
		mat.setBaseColorTexture(null).setEmissiveTexture(null).setMetallicRoughnessTexture(null)
			.setNormalTexture(null).setOcclusionTexture(null)
			.setAlphaMode('OPAQUE').setDoubleSided(false).setEmissiveFactor([0, 0, 0]);
		const shader = d.shader || 'opaque';
		const col = d.color || [1, 1, 1];
		const extras = { shader };
		for (const k of ['specular', 'pan_u', 'pan_v', 'opacity', 'tiling']) if (k in d) extras[k] = d[k];
		mat.setMetallicFactor(d.metallic ?? 0).setRoughnessFactor(d.roughness ?? 0.5);
		if (shader === 'emissive') {
			// unlit-style: black base, colour * texture drives emissive
			mat.setBaseColorFactor([0, 0, 0, 1]).setMetallicFactor(0).setRoughnessFactor(1).setEmissiveFactor(col);
			if (d.texture) {
				mat.setEmissiveTexture(texture(doc, cache, d.texture));
				sampler(mat.getEmissiveTextureInfo());
			}
			const s = (d.emissive_strength ?? 1) * EMISSIVE_SCALE;
			extras.emissive_strength_authored = d.emissive_strength ?? 1;
			if (s !== 1) mat.setExtension('KHR_materials_emissive_strength', emissiveExt.createEmissiveStrength().setEmissiveStrength(s));
		} else if (shader === 'glass') {
			mat.setBaseColorFactor([...col, d.opacity ?? 0.2]).setAlphaMode('BLEND').setMetallicFactor(0)
				.setRoughnessFactor(d.roughness ?? 0.05).setDoubleSided(true);
		} else if (shader === 'crowd') {
			// BaseColor = COLOR_0 (three.js GLTFLoader enables vertexColors automatically)
			mat.setBaseColorFactor([1, 1, 1, 1]).setMetallicFactor(0).setRoughnessFactor(0.85);
			extras.fan_attribute = '_FAN';
		} else {
			// opaque | character | vertexcolor | masked
			mat.setBaseColorFactor([...col, 1]);
			if (d.texture) {
				mat.setBaseColorTexture(texture(doc, cache, d.texture));
				sampler(mat.getBaseColorTextureInfo());
			}
			if (shader === 'masked') mat.setAlphaMode('MASK').setAlphaCutoff(0.5).setDoubleSided(true);
			if (d.emissive || d.emissive_strength) {
				mat.setEmissiveFactor(d.emissive || col);
				const s = d.emissive_strength ?? 1;
				if (s !== 1) mat.setExtension('KHR_materials_emissive_strength', emissiveExt.createEmissiveStrength().setEmissiveStrength(s));
			}
		}
		mat.setExtras(extras);
		report[name] = { shader, ...(d.texture ? { texture: d.texture } : {}) };
	}
	if (!doc.getRoot().listMaterials().some((m) => m.getExtension('KHR_materials_emissive_strength'))) emissiveExt.dispose();
	return report;
}

function fixCrowd(doc) {
	let n = 0;
	for (const mesh of doc.getRoot().listMeshes()) {
		if (!mesh.getName().startsWith('SM_Crowd_')) continue;
		for (const prim of mesh.listPrimitives()) {
			const fan = prim.getAttribute('_FAN');
			if (!fan) throw new Error(`${mesh.getName()} lost its _FAN attribute`);
			const col = prim.getAttribute('COLOR_0');
			const src = col.getArray();
			const k = col.getElementSize();
			const max = src instanceof Uint16Array ? 65535 : src instanceof Uint8Array ? 255 : 1;
			const dst = new Uint8Array(col.getCount() * 4);
			for (let i = 0; i < col.getCount(); i++) {
				for (let c = 0; c < 3; c++) dst[i * 4 + c] = Math.round(Math.min(1, Math.max(0, src[i * k + c] / max)) * 255);
				dst[i * 4 + 3] = 255;
			}
			col.setArray(dst).setType('VEC4').setNormalized(true);
			const uv = prim.getAttribute('TEXCOORD_0');
			if (uv) prim.setAttribute('TEXCOORD_0', null);
			n++;
		}
	}
	return n;
}

// TEXCOORD_0 is only kept where the primitive's material samples a texture (characters have
// none; the bowl/truss/benches only carry generator box-projection UVs).
function dropUnusedUVs(doc) {
	let n = 0;
	for (const mesh of doc.getRoot().listMeshes()) {
		for (const prim of mesh.listPrimitives()) {
			const m = prim.getMaterial();
			if (m && (m.getBaseColorTexture() || m.getEmissiveTexture())) continue;
			if (prim.getAttribute('TEXCOORD_0')) { prim.setAttribute('TEXCOORD_0', null); n++; }
		}
	}
	return n;
}

function summarize(doc) {
	const meshes = {};
	let tris = 0;
	for (const node of doc.getRoot().listNodes()) {
		const mesh = node.getMesh();
		if (!mesh) continue;
		let t = 0;
		let v = 0;
		const attrs = new Set();
		for (const p of mesh.listPrimitives()) {
			const idx = p.getIndices();
			t += (idx ? idx.getCount() : p.getAttribute('POSITION').getCount()) / 3;
			v += p.getAttribute('POSITION').getCount();
			for (const s of p.listSemantics()) attrs.add(s);
		}
		tris += t;
		meshes[node.getName()] = {
			tris: t, verts: v,
			materials: [...new Set(mesh.listPrimitives().map((p) => p.getMaterial()?.getName()))],
			attributes: [...attrs].sort(),
			translation: node.getTranslation(), rotation: node.getRotation(), scale: node.getScale(),
			skinned: !!node.getSkin(),
		};
	}
	const animations = {};
	for (const a of doc.getRoot().listAnimations()) {
		let dur = 0;
		for (const s of a.listSamplers()) dur = Math.max(dur, s.getInput().getMax([0])[0]);
		animations[a.getName()] = +dur.toFixed(6);
	}
	const skins = doc.getRoot().listSkins().map((s) => s.listJoints().map((j) => j.getName()));
	return { tris, meshes, animations, skins };
}

const stats = {};
for (const job of JOBS) {
	const doc = await io.read(path.join(BUILD, job.src));
	doc.setLogger(new Logger(Logger.Verbosity.ERROR)); // quantize() warns about every out-of-[0,1] UV set it skips
	const materials = rewriteMaterials(doc);
	if (job.name.startsWith('arena')) fixCrowd(doc);
	dropUnusedUVs(doc);
	if (job.kind === 'character') {
		await doc.transform(resample({ tolerance: 1e-5 }));
	}
	await doc.transform(dedup({ propertyTypes: [PropertyType.ACCESSOR, PropertyType.TEXTURE] }), prune({ keepAttributes: true, keepLeaves: true }));
	if (job.compress) {
		await doc.transform(
			reorder({ encoder: MeshoptEncoder, target: 'size' }),
			// POSITION and the crowd's _FAN stay float32: no node dequantisation transforms
			quantize({ pattern: /^(NORMAL|TEXCOORD_\d+|COLOR_\d+|WEIGHTS_\d+)$/, quantizeNormal: 8, quantizeTexcoord: 12, quantizeColor: 8, quantizeWeight: 8 }),
		);
		// gltf-transform 4.2.1's quantize() only declares KHR_mesh_quantization when POSITION is
		// quantized (isQuantizedPrimitive checks POSITION for every semantic); we quantize normals
		// to BYTE, which core glTF does not allow, so declare it ourselves.
		const quantized = doc.getRoot().listMeshes().flatMap((m) => m.listPrimitives()).some((p) => {
			const n = p.getAttribute('NORMAL');
			const uv = p.getAttribute('TEXCOORD_0');
			return (n && n.getComponentType() !== 5126) || (uv && [5120, 5122].includes(uv.getComponentType()));
		});
		if (quantized) doc.createExtension(KHRMeshQuantization).setRequired(true);
		doc.createExtension(EXTMeshoptCompression).setRequired(true)
			.setEncoderOptions({ method: EXTMeshoptCompression.EncoderMethod.FILTER });
	}
	// drop extensions Blender declared that no longer have users (e.g. KHR_materials_specular)
	const keep = new Set(['EXT_meshopt_compression', 'KHR_mesh_quantization', 'KHR_materials_emissive_strength']);
	for (const ext of doc.getRoot().listExtensionsUsed()) if (!keep.has(ext.extensionName)) ext.dispose();
	const out = path.join(OUT, job.out);
	fs.mkdirSync(path.dirname(out), { recursive: true });
	await io.write(out, doc);
	const s = summarize(doc);
	stats[job.name] = {
		file: job.out, bytes: fs.statSync(out).size, compression: job.compress ? 'EXT_meshopt_compression+KHR_mesh_quantization' : 'none',
		extensionsUsed: doc.getRoot().listExtensionsUsed().map((e) => e.extensionName), materials, ...s,
	};
	console.log(`POST ${job.out} ${(stats[job.name].bytes / 1048576).toFixed(2)} MB tris=${s.tris} anims=${Object.keys(s.animations).length}`);
}
fs.writeFileSync(path.join(BUILD, 'post_stats.json'), JSON.stringify(stats, null, 1));
