import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ScanView from '../views/ScanView.vue'
import ReportsView from '../views/ReportsView.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HomeView },
    { path: '/scan/:id', component: ScanView },
    { path: '/reports', component: ReportsView },
  ],
})
