<script setup>
import { RouterView } from "vue-router";
</script>

<template>
  <RouterView v-slot="{ Component, route: currentRoute }">
    <Transition name="page-fade" mode="out-in">
      <component :is="Component" :key="currentRoute.name" />
    </Transition>
  </RouterView>
</template>
