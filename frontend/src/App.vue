<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">主数据治理与参考数据管理平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">覆盖主数据抽取、标准化清洗、去重合并、金记录发布与下游订阅分发的治理平台</span>
        <span class="head-user">当前值班：数据工程组</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "源系统登记", path: "/source_system" }, { label: "主数据实体", path: "/entity_model" }, { label: "记录抽取作业", path: "/record_extract" }, { label: "标准化清洗", path: "/std_cleanse" }, { label: "重复检测器", path: "/dup_detect" }, { label: "金记录合并", path: "/golden_merge" }, { label: "金记录发布", path: "/golden_publish" }, { label: "下游订阅方", path: "/subscriber_mgr" }, { label: "分发任务", path: "/dist_task" }, { label: "血缘关系图", path: "/lineage_graph" }, { label: "质量规则库", path: "/quality_rule" }, { label: "质量报告", path: "/quality_result" }, { label: "合并复核队列", path: "/merge_review" }, { label: "版本回滚器", path: "/version_rollback" }, { label: "同步游标", path: "/sync_cursor" }, { label: "标识交叉映射", path: "/id_cross_map" }, { label: "分发回执中心", path: "/dist_receipt" }, { label: "实体变更审批", path: "/model_change" }, { label: "变更通知跟进", path: "/change_notification" }, { label: "刷新回执中心", path: "/refresh_receipt" }, { label: "治理看板数据", path: "/stats_overview" }, { label: "参考数据管理", path: "/ref_data_mgr" }]
</script>
