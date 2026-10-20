import {queryAgent} from './api.mjs';
import {showError} from './ui.mjs';
export function bindAgent(context, review) {
  let active, version = 0;
  const agent = document.querySelector('#agent');
  agent.addEventListener('submit',async event => {
    event.preventDefault(); const current = ++version; active?.abort(); active = new AbortController();
    const form = event.currentTarget, data = new FormData(form), button = form.querySelector('button');
    const trace = document.querySelector('#trace'), answer = document.querySelector('#answer'); trace.textContent = ''; answer.textContent = ''; button.disabled = true;
    try {
      const result = await queryAgent({...context(),message:data.get('message'),engine:data.get('engine')},item => {
        if (current !== version) return;
        if (item.type !== 'complete') { const visible = {...item}; if (visible.result) { const {proposal,...rest} = visible.result; visible.result = rest; } trace.textContent += JSON.stringify(visible,null,2) + '\n'; }
      },active.signal);
      if (current !== version) return;
      answer.textContent = result.answer;
      const proposal = result.results?.prepare_personal_change; if (proposal?.proposal) review(proposal);
    } catch(error) { if (current === version && error.name !== 'AbortError') showError(error); } finally { if (current === version) button.disabled = false; }
  });
  return () => { version++; active?.abort(); active = null; agent.querySelector('button').disabled = false; };
}
