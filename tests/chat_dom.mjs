// Minimal DOM for chat interaction tests. All message rendering must use text nodes.
class Node {
  constructor(tag) { this.tagName=tag.toUpperCase(); this.children=[]; this.handlers={}; this.attributes={}; this.style={}; this.dataset={}; this.value=''; this.ownText=''; this.className=''; }
  set textContent(text) { this.ownText=String(text); this.children=[]; }
  get textContent() { return this.ownText+this.children.map(child=>child.textContent).join(' '); }
  append(...nodes) { for(const node of nodes) { node.parent=this; this.children.push(node); } }
  replaceChildren(...nodes) { this.ownText=''; this.children=[]; this.append(...nodes); }
  remove() { if(this.parent)this.parent.children=this.parent.children.filter(node=>node!==this); }
  addEventListener(type,handler) { this.handlers[type]=handler; }
  setAttribute(key,value) { this.attributes[key]=value; }
  removeAttribute(key) { delete this.attributes[key]; }
  get classList() { return {add:name=>{this.className+=' '+name;},remove:name=>{this.className=this.className.split(' ').filter(item=>item!==name).join(' ');}}; }
  querySelector(selector) { return all(this).find(node=>selector[0]==='.'?node.className.split(' ').includes(selector.slice(1)):selector==='[name="engine"]'?node.name==='engine':node.tagName===selector.toUpperCase()) || null; }
  focus() { this.focused=true; }
  requestSubmit() { return this.handlers.submit({preventDefault(){}}); }
}
export const all = root => root.children.flatMap(node=>[node,...all(node)]);
export function chatDOM(extra = []) {
  const original=globalThis.document;
  const ids=Object.fromEntries([['agent','form'],['chat-messages','div'],['chat-input','textarea'],['chat-send','button'],['chat-stop','button'],['new-chat','button'],...extra].map(([id,tag])=>[id,new Node(tag)]));
  const engine=new Node('select'); engine.name='engine'; engine.value='llm';
  ids.agent.append(ids['chat-input'],engine,ids['chat-send'],ids['chat-stop']);
  globalThis.document={createElement:tag=>new Node(tag),querySelector:selector=>ids[selector.slice(1)] || null};
  return {...ids,engine,restore(){globalThis.document=original;}};
}
export function completionStream(result) {
  return new Response('data: '+JSON.stringify({type:'complete',response:result})+'\n\n');
}
