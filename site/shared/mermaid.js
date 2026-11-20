// Import only when a view has diagram text. The module is shared by both Pages views.
let renderer;
export async function renderDiagram(id, source) {
  renderer ??= import('https://cdn.jsdelivr.net/npm/mermaid@11.12.1/dist/mermaid.esm.min.mjs')
    .then(({default: mermaid}) => {
      mermaid.initialize({startOnLoad: false, securityLevel: 'strict'});
      return mermaid;
    });
  const mermaid = await renderer;
  return (await mermaid.render(id, source)).svg;
}
