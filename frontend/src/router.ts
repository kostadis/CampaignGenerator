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
        path: 'vtt',
        name: 'vtt-summary',
        component: () => import('./views/session/VttSummary.vue'),
      },
      {
        path: 'extract',
        name: 'scene-extraction',
        component: () => import('./views/session/SceneExtraction.vue'),
      },
      {
        path: 'editor',
        name: 'editor',
        component: () => import('./views/session/SessionDocEditor.vue'),
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
    path: '/experimental',
    component: () => import('./views/ExperimentalTools.vue'),
    children: [
      { path: '', redirect: '/experimental/enhance-recap' },
      {
        path: 'enhance-recap',
        name: 'enhance-recap',
        component: () => import('./views/experimental/EnhanceRecap.vue'),
      },
      {
        path: 'narrative',
        name: 'session-narrative',
        component: () => import('./views/experimental/SessionNarrative.vue'),
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
