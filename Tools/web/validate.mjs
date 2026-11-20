// Khronos glTF-Validator over every GLB in <assets_dir>. The validator cannot read
// EXT_meshopt_compression buffers, so compressed files are decoded in memory first (the
// KHR_mesh_quantization formats are kept and validated). Exits 1 on any error.
//   node Tools/web/validate.mjs <assets_dir>
import fs from 'node:fs';
import path from 'node:path';
import { Logger, NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import validator from 'gltf-validator';
import { MeshoptDecoder } from 'meshoptimizer';

await MeshoptDecoder.ready;
const io = new NodeIO().setLogger(new Logger(Logger.Verbosity.ERROR))
	.registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'meshopt.decoder': MeshoptDecoder });
const dir = process.argv[2];
const files = fs.readdirSync(dir, { recursive: true }).filter((f) => f.endsWith('.glb')).sort();
// expected for Blender skinned exports: the skinned meshes sit under the identity 'Armature' node
const IGNORE = new Set(['NODE_SKINNED_MESH_NON_ROOT', 'UNUSED_OBJECT']);
let errors = 0;
for (const f of files) {
	let bytes = new Uint8Array(fs.readFileSync(path.join(dir, f)));
	const doc = await io.readBinary(bytes);
	const meshopt = doc.getRoot().listExtensionsUsed().find((e) => e.extensionName === 'EXT_meshopt_compression');
	if (meshopt) {
		meshopt.dispose();
		bytes = await io.writeBinary(doc);
	}
	const r = await validator.validateBytes(bytes, { maxIssues: 200 });
	const issues = r.issues.messages.filter((m) => m.severity <= 1 && !IGNORE.has(m.code));
	errors += r.issues.numErrors;
	console.log(`VALIDATE ${f}${meshopt ? ' (meshopt decoded)' : ''}: ${r.issues.numErrors} errors, ${issues.filter((m) => m.severity === 1).length} warnings`);
	for (const m of issues.slice(0, 10)) console.log(`   ${m.severity ? 'W' : 'E'} ${m.code} ${m.pointer ?? ''} ${m.message}`);
}
process.exit(errors ? 1 : 0);
