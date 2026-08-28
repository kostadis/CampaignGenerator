<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfigStore } from '../../stores/config'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import PathField from '../../components/shared/PathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

const pdfs = ref('')
const partyConfig = ref('')
const output = ref('')
const outputDir = ref('')

const pdfList = computed(() =>
  pdfs.value.split('\n').map(l => l.trim()).filter(Boolean)
)

const ready = computed(() => pdfList.value.length > 0)

// Which mode the current inputs select. Roster mode needs a party config AND
// no output location — an explicit one suppresses roster naming and archival
// (FR-017), and that is invisible unless the page says so.
//
// This must mirror what the ROUTER actually forwards, not what the fields hold:
// it sends --output only for a single PDF, so a filled "output file" box with
// several PDFs queued reaches the CLI as no output flag at all. Reading the
// fields naively would announce "archival is off" for a run that archives.
const explicitOutput = computed(() =>
  !!((pdfList.value.length === 1 && output.value.trim()) || outputDir.value.trim())
)
const rosterMode = computed(() => !!partyConfig.value.trim() && !explicitOutput.value)

const runParams = computed(() => ({
  pdfs: pdfList.value,
  party_config: partyConfig.value,
  output: output.value,
  output_dir: outputDir.value,
  model: config.model || undefined,
}))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>D&amp;D Sheet &rarr; Markdown</h2>
      <p class="subtitle">Convert D&amp;D Beyond PDF character sheets to structured markdown via Claude vision.</p>
    </div>

    <div class="form-grid">
      <div class="form-section">
        <MultiPathField v-model="pdfs" label="PDF files" required resolve-base="campaign"
          help="One PDF path per line." />
      </div>

      <div class="form-section">
        <PathField v-model="partyConfig" label="Party config (party.yaml)" resolve-base="campaign"
          help="The campaign's config/party.yaml. Sets it to name each sheet from the roster, archive the sheet it replaces under old/level/&lt;N&gt;/, and write the roster's player over the one in the export — a D&amp;D Beyond download stamps the downloader's name into every sheet. Leave blank for the old behaviour." />
      </div>

      <div class="form-section">
        <PathField v-model="output" label="Output file (single PDF)" is-output resolve-base="campaign"
          help="For a single PDF. Leave blank to let the roster name the file." />
        <PathField v-model="outputDir" label="Output directory (multiple PDFs)" is-output resolve-base="campaign"
          help="One .md file per PDF, named after the input. Leave blank to let the roster name the files." />
      </div>

      <div :class="['info-box', rosterMode ? 'mode-roster' : 'mode-legacy']">
        <template v-if="rosterMode">
          <strong>Roster mode.</strong> Each sheet is matched to a roster entry by the
          character name on it, written to the path the roster declares, and any sheet
          already there is archived under <code>old/level/&lt;N&gt;/</code> first. A name
          that isn't in the roster is refused — nothing is written or moved.
        </template>
        <template v-else-if="explicitOutput && partyConfig.trim()">
          <strong>Roster naming and archival are off</strong> because an output location is
          set. Clear both output fields to turn them back on.
        </template>
        <template v-else>
          <strong>Legacy mode.</strong> Each sheet is named after its source PDF. Set a
          party config above to name sheets from the roster and archive what they replace.
        </template>
      </div>

      <div v-if="pdfList.length > 1 && output.trim()" class="info-box">
        --output only works for a single PDF. Use output directory for multiple files.
      </div>

      <RunPanel
        selection-service="setup"
        endpoint="/api/setup/run/dnd-sheet"
        :params="runParams"
        :disabled="!ready"
        label="Convert Sheet"
        @done="() => {}"
      />
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 700px; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface0);
}
.form-section:last-child { border-bottom: none; }

.info-box {
  padding: 10px 14px; background: #3a2a1e; border-radius: 4px;
  font-size: 11px; color: var(--peach); line-height: 1.5;
}
.info-box code {
  font-family: var(--font-mono, monospace); font-size: 10px;
  background: rgba(0, 0, 0, 0.25); padding: 1px 4px; border-radius: 3px;
}
.info-box.mode-roster { background: var(--bg-surface0); color: var(--text-sub); }
.info-box.mode-legacy { background: var(--bg-surface0); color: var(--text-muted); }
</style>
