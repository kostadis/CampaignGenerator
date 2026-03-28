<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfigStore } from '../../stores/config'
import MultiPathField from '../../components/shared/MultiPathField.vue'
import PathField from '../../components/shared/PathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

const pdfs = ref('')
const output = ref('')
const outputDir = ref('')

const pdfList = computed(() =>
  pdfs.value.split('\n').map(l => l.trim()).filter(Boolean)
)

const ready = computed(() => pdfList.value.length > 0)

const runParams = computed(() => ({
  pdfs: pdfList.value,
  output: output.value,
  output_dir: outputDir.value,
  model: config.model,
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
        <MultiPathField v-model="pdfs" label="PDF files" required
          help="One PDF path per line." />
      </div>

      <div class="form-section">
        <PathField v-model="output" label="Output file (single PDF)" is-output
          help="For a single PDF. Leave blank to print to terminal." />
        <PathField v-model="outputDir" label="Output directory (multiple PDFs)" is-output
          help="One .md file per PDF, named after the input." />
      </div>

      <div v-if="pdfList.length > 1 && output.trim()" class="info-box">
        --output only works for a single PDF. Use output directory for multiple files.
      </div>

      <RunPanel
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
</style>
