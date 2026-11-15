import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const engine=fileURLToPath(new URL('./ontautology.py',import.meta.url));
const result=spawnSync(process.platform==='win32'?'python':'python3',['-S',engine,...process.argv.slice(2)],{stdio:'inherit',shell:false});
if(result.error){console.error(result.error.message);process.exit(1)}
process.exit(result.status??1);
