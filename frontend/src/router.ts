import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/workflow/config',
  },
  {
    path: '/workflow',
    component: () => import('./views/SessionWorkflow.vue'),
    children: [
      {
        path: '',
        redirect: '/workflow/config',
      },
      {
        path: 'config',
        name: 'session-config',
        component: () => import('./views/session/SessionConfig.vue'),
      },
      {
        path: 'editor',
        name: 'editor',
        component: () => import('./views/session/SessionDocEditor.vue'),
      },
      {
        path: 'editor/review',
        name: 'editor-review',
        component: () => import('./views/session/ReviewAssemble.vue'),
      },
    ],
  },
  {
    path: '/grounding',
    component: () => import('./views/GroundingDocs.vue'),
    children: [
      {
        path: '',
        redirect: '/grounding/campaign-state',
      },
      {
        path: 'campaign-state',
        name: 'campaign-state',
        component: () => import('./views/grounding/CampaignState.vue'),
      },
      {
        path: 'distill',
        name: 'distill-world-state',
        component: () => import('./views/grounding/DistillWorldState.vue'),
      },
      {
        path: 'world-state',
        redirect: '/grounding/distill',
      },
      {
        path: 'party',
        name: 'party-document',
        component: () => import('./views/grounding/PartyDocument.vue'),
      },
      {
        path: 'planning',
        name: 'planning-document',
        component: () => import('./views/grounding/PlanningDocument.vue'),
      },
    ],
  },
  {
    path: '/ensemble',
    component: () => import('./views/EnsembleWorkflow.vue'),
    children: [
      { path: '', redirect: '/ensemble/setup' },
      {
        path: 'setup',
        name: 'ensemble-setup',
        component: () => import('./views/ensemble/EnsembleSetup.vue'),
      },
      {
        path: 'extract',
        name: 'ensemble-extract',
        component: () => import('./views/ensemble/EnsembleExtract.vue'),
      },
      {
        path: 'bundle',
        name: 'ensemble-bundle',
        component: () => import('./views/ensemble/EnsembleBundle.vue'),
      },
      {
        path: 'synthesize',
        name: 'ensemble-synthesize',
        component: () => import('./views/ensemble/EnsembleSynthesize.vue'),
      },
    ],
  },
  {
    path: '/prep',
    component: () => import('./views/PrepTools.vue'),
    children: [
      { path: '', redirect: '/prep/session-prep' },
      {
        path: 'session-prep',
        name: 'session-prep',
        component: () => import('./views/prep/SessionPrep.vue'),
      },
      {
        path: 'npc-table',
        name: 'npc-table',
        component: () => import('./views/prep/NpcTable.vue'),
      },
      {
        path: 'query',
        name: 'query-summaries',
        component: () => import('./views/prep/QuerySummaries.vue'),
      },
      {
        path: 'connections',
        name: 'connection-graph',
        component: () => import('./views/prep/ConnectionGraph.vue'),
      },
    ],
  },
  {
    path: '/setup',
    component: () => import('./views/SetupTools.vue'),
    children: [
      { path: '', redirect: '/setup/dnd-sheet' },
      {
        path: 'dnd-sheet',
        name: 'dnd-sheet',
        component: () => import('./views/setup/DndSheet.vue'),
      },
      {
        path: 'make-tracking',
        name: 'make-tracking',
        component: () => import('./views/setup/MakeTracking.vue'),
      },
    ],
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('./views/Settings.vue'),
  },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
