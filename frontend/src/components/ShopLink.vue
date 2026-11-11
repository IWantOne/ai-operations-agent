<script setup>
import { computed, inject, onMounted } from "vue";
import { shopRoute, routeHref } from "../api/platform";
const props = defineProps({ id: {type: String, required: true} });
const { navigate, accountOverview, loadAccounts } = inject("workbench");
const name = computed(() => accountOverview.value?.shops.find(s => String(s.id) === props.id)?.name || props.id);
onMounted(() => loadAccounts());
</script>
<template>
  <a :href="routeHref(shopRoute(id))" @click.exact.prevent="navigate(shopRoute(id))">{{ name }}</a>
</template>
