<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useConfigStore } from '../stores/config'
import BackendModelPicker from './shared/BackendModelPicker.vue'

const props = defineProps<{ since: number | null; until: number | null; reviewId?: string }>()
const emit = defineEmits<{ reviewChanged:[value:string]; selectionSaved:[path:string]; reportReady:[path:string] }>()
const base = '/api/grounding/summary-native/claims'
const busy = ref(false), message = ref(''), diagnostic = ref('')
const selection = ref<any | null>(null), selectionFile = ref(''), candidateFile = ref('')
const candidateArtifact = ref('')
const candidateArtifactKind = ref<'extract'|'import'|''>('')
const reviewer = ref('GM')
// No default review id: the CLI declares none, so the GM names it explicitly (X/XII).
const review = ref(props.reviewId ?? ''), reportFile = ref(''), report = ref<any | null>(null)
// Empty = not sent: `claims select` resolves grounding.yaml summary_native.out_root (or its declared default).
const outRoot = ref('')
const backend = ref(''), model = ref(''), useExtraction = ref(false)
// The claims CLI's extract defaults are summary_native extract's: grounding.yaml summary_native.extract.
const config = useConfigStore()
const storedSelection = computed(() => {
  const b = (config.groundingConfig?.summary_native?.extract ?? {}) as { backend?: string | null; model?: string | null }
  return { backend: b.backend || '', model: b.model || '' }
})
const configuredOutRoot = computed(() => {
  const value = config.groundingConfig?.summary_native?.out_root
  return typeof value === 'string' ? value : ''
})
const maxTokens = ref<number|''>(''), chunkChars = ref<number|''>(''), forceExtraction = ref(false)
const confirmedSources = ref<string[]>([]), confirmedChunks = ref<string[]>([])
const chunkScopeConfirmed = ref(false)
const assistanceUnbound = computed(() => (useExtraction.value || candidateFile.value.trim() !== '') && !candidateArtifact.value)
const findingItem = ref(''), decisionRevision = ref(0), disposition = ref<'dismiss'|'accept_uncertainty'>('dismiss'), rationale = ref('')
const sourceRows = computed(() => selection.value?.sources ?? [])
const chunkRows = computed(() => selection.value?.chunks ?? [])
const exactConfirmed = computed(() => sourceRows.value.length > 0
  && confirmedSources.value.length === sourceRows.value.length
  && chunkScopeConfirmed.value)
const canonicalSelection = computed(() => selection.value ? {
  ...selection.value,
  // Required source closure is immutable. Chunk checkboxes are the explicit
  // model scope and an empty list intentionally means no model extraction.
  sources: sourceRows.value,
  chunks: chunkRows.value.filter((chunk:any) => confirmedChunks.value.includes(chunk.chunk_id)),
} : null)

async function command(path:string, payload:object) {
  busy.value=true; message.value=''; diagnostic.value=''
  try {
    const response=await fetch(`${base}/${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    const body=await response.json()
    if(!response.ok) throw new Error(body.message||body.detail||`Claims request failed (${response.status})`)
    if(body.ok===false) diagnostic.value=body.message||body.code||'Claims work remains blocked.'
    else message.value=body.message||'Completed.'
    return body
  } catch(error) { diagnostic.value=error instanceof Error?error.message:String(error); return null }
  finally { busy.value=false }
}
function clearDownstream(){selectionFile.value='';candidateArtifact.value='';reportFile.value='';report.value=null;emit('selectionSaved','');emit('reportReady','')}
async function selectSources(){if(props.since===null||props.until===null)return;clearDownstream();const body=await command('select',{since:props.since,until:props.until,...(outRoot.value.trim()?{out_root:outRoot.value.trim()}:{})});selection.value=body?.data?.selection??null;confirmedSources.value=[];confirmedChunks.value=[];chunkScopeConfirmed.value=false;if(!selection.value)diagnostic.value=body?.message||'No source selection was returned.'}
async function saveSelection(){if(!canonicalSelection.value)return;const body=await command('selection/save',{selection:canonicalSelection.value,reviewer:reviewer.value});selectionFile.value=body?.data?.path??selectionFile.value;if(selectionFile.value)emit('selectionSaved',selectionFile.value)}
async function materializeChunks(){if(!selection.value)return;clearDownstream();const body=await command('selection/chunks',{selection:selection.value,source_ids:confirmedSources.value});if(body?.data?.selection){selection.value=body.data.selection;confirmedChunks.value=body.data.selection.chunks.map((item:any)=>item.chunk_id);chunkScopeConfirmed.value=false}}
async function extract(){if(!canonicalSelection.value?.chunks?.length){diagnostic.value='Select at least one explicit chunk before model extraction.';return}candidateArtifact.value='';candidateArtifactKind.value='';report.value=null;reportFile.value='';emit('reportReady','');const body=await command('extract',{selection:selectionFile.value,...(backend.value?{backend:backend.value}:{}),...(model.value?{model:model.value}:{}),...(typeof maxTokens.value==='number'?{max_tokens:maxTokens.value}:{}),...(typeof chunkChars.value==='number'?{chunk_chars:chunkChars.value}:{}),...(forceExtraction.value?{force:true}:{})});candidateArtifact.value=body?.data?.path??'';candidateArtifactKind.value=candidateArtifact.value?'extract':'';if(!candidateArtifact.value)diagnostic.value=body?.message||'Extraction returned no bound run artifact; review remains unavailable.'}
async function importCandidates(){candidateArtifact.value='';candidateArtifactKind.value='';report.value=null;reportFile.value='';emit('reportReady','');const body=await command('import',{selection:selectionFile.value,candidates:candidateFile.value});candidateArtifact.value=body?.data?.path??'';candidateArtifactKind.value=candidateArtifact.value?'import':''}
async function createReview(){await command('review',{selection:selectionFile.value,review:review.value.trim(),...(candidateArtifact.value?{candidates:candidateArtifact.value}:{})})}
async function check(){const body=await command('check',{selection:selectionFile.value,review:review.value.trim()});const data=body?.data??{};report.value=data.report??data.result?.report??(body?{outcome:body.ok?'complete':'blocked',findings:[],coverage_limitations:[body.message].filter(Boolean)}:null);reportFile.value=data.paths?.[0]??data.path??reportFile.value;if(reportFile.value)emit('reportReady',reportFile.value)}
async function show(){const body=await command('show',{report:reportFile.value});report.value=body?.data?.report??null}
async function prepareDisposition(){await command('disposition',{review:review.value.trim(),item:findingItem.value,expected_decision_revision:decisionRevision.value,disposition:disposition.value,rationale:rationale.value})}
watch([backend,model,maxTokens,chunkChars,forceExtraction],()=>{if(candidateArtifactKind.value==='extract'){candidateArtifact.value='';candidateArtifactKind.value=''}})
watch(candidateFile,()=>{if(candidateArtifactKind.value==='import'){candidateArtifact.value='';candidateArtifactKind.value=''}})
watch(()=>props.reviewId,value=>{if(value!==undefined&&value!==review.value)review.value=value})
// A loaded selection belongs to the out root it was selected under; a different root needs a fresh select.
watch(outRoot,()=>{if(selection.value){selection.value=null;confirmedSources.value=[];confirmedChunks.value=[];chunkScopeConfirmed.value=false;clearDownstream()}})
watch(useExtraction,value=>{if(!value&&candidateArtifactKind.value==='extract'){candidateArtifact.value='';candidateArtifactKind.value=''}})
</script>

<template>
  <section class="claims" data-test="grounding-claims">
    <h2>Claims and evidence review</h2>
    <p>Select and confirm the exact source and chunk scope before importing or extracting candidate meanings.</p>
    <label>Out root <span class="optional">(optional)</span><input v-model="outRoot" autocomplete="off" data-test="claims-out-root" :placeholder="configuredOutRoot"><span class="hint">Empty uses grounding.yaml summary_native.out_root.</span></label>
    <button :disabled="busy||since===null||until===null" @click="selectSources">Load exact source selection</button>
    <p v-if="!selection" class="empty" data-test="claims-selection-null">No current selection. Load a chapter range to inspect required evidence.</p>
    <div v-else class="scope">
      <h3>Required sources</h3>
      <label v-for="source in sourceRows" :key="source.source_id"><input v-model="confirmedSources" type="checkbox" :value="source.source_id" @change="clearDownstream"> <code>{{ source.path }}</code> — {{ source.source_audience }} / {{ source.applicability }}</label>
      <h3>Selected chunks</h3>
      <label v-for="chunk in chunkRows" :key="chunk.chunk_id"><input v-model="confirmedChunks" type="checkbox" :value="chunk.chunk_id" @change="clearDownstream"> <code>{{ chunk.locator }}</code> ({{ chunk.sha256 }})</label>
      <button type="button" :disabled="busy||confirmedSources.length===0" @click="materializeChunks">Materialize whole-source chunks</button>
      <label><input v-model="chunkScopeConfirmed" type="checkbox"> Confirm this exact chunk scope, including an intentional empty scope</label>
      <!-- RESERVED, NOT WIRED (#548 review item 8): the GM's resolution of an unresolved scope entry in this
           selection. Its CLI subcommand is being added under `summary_native claims ...`; the route slot is
           marked in server/routers/summary_native.py. Wire the control here once that argv is final —
           do not guess its flags. -->
    </div>
    <label>Reviewer <input v-model="reviewer"></label><label>Confirmed selection file <input v-model="selectionFile" readonly placeholder="Saved by the claims service after confirmation"></label>
    <button :disabled="busy||!reviewer||!exactConfirmed" @click="saveSelection">Save exact confirmation</button>
    <fieldset><legend>Optional candidate assistance</legend><label><input v-model="useExtraction" type="checkbox"> Run optional model extraction</label><div class="pair"><BackendModelPicker v-model:backend="backend" v-model:model="model" config-key="summary_native.extract" :stored-backend="storedSelection.backend" :stored-model="storedSelection.model" /></div><label>Maximum output tokens <input v-model.number="maxTokens" type="number" min="1"></label><label>Chunk character bound <input v-model.number="chunkChars" type="number" min="1"></label><label><input v-model="forceExtraction" type="checkbox"> Force a fresh extraction run</label><button :disabled="busy||!selectionFile||!useExtraction||confirmedChunks.length===0" @click="extract">Extract selected chunks</button><p v-if="useExtraction&&confirmedChunks.length===0" class="empty">Select at least one explicit chunk to run model extraction. Empty scope never expands implicitly.</p><label>Candidate import file <input v-model="candidateFile"></label><button :disabled="busy||!selectionFile||!candidateFile" @click="importCandidates">Import candidates</button><label>Persisted candidate artifact <input :value="candidateArtifact" readonly></label></fieldset>
    <p v-if="assistanceUnbound" class="diagnostic">Selected assistance has no persisted run or import artifact. Complete or retry it before creating the review.</p><label>Review ID <input v-model="review" autocomplete="off" placeholder="required — no default" data-test="claims-review-id" @input="emit('reviewChanged',review)"></label><p v-if="!review.trim()" class="empty">Name the shared review explicitly; there is no default review.</p><button :disabled="busy||!selectionFile||!review.trim()||assistanceUnbound" @click="createReview">Create or refresh claim review</button><button :disabled="busy||!selectionFile||!review.trim()||assistanceUnbound" @click="check">Run deterministic checks</button>
    <label>Report file <input v-model="reportFile"></label><button :disabled="busy||!reportFile" @click="show">Refresh current report</button>
    <section v-if="report" class="report" data-test="claims-report"><h3>Check coverage</h3><p>Outcome: <strong>{{ report.outcome }}</strong></p><ul><li v-for="item in report.coverage_limitations||[]" :key="item">{{ item }}</li></ul><p>{{ report.findings?.length??0 }} finding(s).</p></section>
    <fieldset><legend>Prepare a displayed finding alternative</legend><label>Finding item <input v-model="findingItem"></label><label>Expected decision revision <input v-model.number="decisionRevision" type="number" min="0"></label><label>Alternative <select v-model="disposition"><option value="dismiss">Evidence-backed dismissal</option><option value="accept_uncertainty">Accept displayed uncertainty</option></select></label><label>Exact rationale <textarea v-model="rationale"></textarea></label><button :disabled="busy||!review.trim()||!findingItem||!rationale" @click="prepareDisposition">Prepare for shared review</button></fieldset>
    <p v-if="message" aria-live="polite">{{ message }}</p><p v-if="diagnostic" class="diagnostic" role="alert">{{ diagnostic }}</p>
  </section>
</template>

<style scoped>
/* Matches the Summary-native page it sits on: 12px step headings, 11px labels, 11px mono inputs,
   neutral small buttons. */
.claims { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--bg-surface0); font-size: 11px; color: var(--text-sub); min-width: 0; max-width: 100%; }
h2 { font-size: 12px; font-weight: 700; color: var(--text); margin: 0 0 8px; }
h3 { font-size: 11px; font-weight: 700; color: var(--text); margin: 10px 0 4px; }
p { margin: 4px 0 8px; color: var(--text-muted); }
.scope, .report, fieldset { display: grid; gap: 6px; margin-block: 10px; min-width: 0; }
fieldset { padding: 10px; border: 1px solid var(--bg-surface0); border-radius: 4px; }
legend { padding: 0 4px; font-size: 11px; font-weight: 700; color: var(--text); }
label { display: block; min-width: 0; margin-bottom: 8px; font-weight: 600; color: var(--text-sub); overflow-wrap: anywhere; }
label:has(> input[type=checkbox]) { display: flex; align-items: center; gap: 6px; font-weight: 400; margin-bottom: 4px; }
input[type=checkbox] { accent-color: var(--mauve); }
input:not([type=checkbox]), select, textarea {
  display: block; width: min(38rem, 100%); max-width: 100%; box-sizing: border-box; margin-top: 3px;
  padding: 6px 8px; border: 1px solid var(--bg-surface1); border-radius: 4px; outline: none;
  background: var(--bg-base); color: var(--text); font-family: var(--mono); font-size: 11px;
}
input:focus, select:focus, textarea:focus { border-color: var(--mauve); }
code { font-family: var(--mono); font-size: 10px; overflow-wrap: anywhere; }
button { margin: 0 6px 8px 0; font-size: 11px; padding: 4px 10px; background: var(--bg-surface0); color: var(--text); justify-self: start; }
.pair { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(200px, 100%), 1fr)); gap: 0 12px; }
.diagnostic { border-left: 3px solid var(--red); padding: 6px 8px; color: var(--red); }
.empty { color: var(--text-muted); }
.optional { font-weight: 400; color: var(--text-muted); }
.hint { display: block; margin-top: 2px; font-weight: 400; font-size: 10px; color: var(--text-muted); }
</style>
