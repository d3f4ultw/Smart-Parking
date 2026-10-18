<template>
  <div class="vision-editor-layout">
    <slot />
  </div>
</template>

<style>
html, body, #__nuxt { width: 100%; height: 100%; margin: 0; }
body { overflow: hidden; }
.vision-editor-layout {
  width: 100vw;
  height: 100dvh;
  overflow: hidden;
  color-scheme: dark;
  --admin-foreground: #e9edf4;
  --admin-muted: #9caabd;
  --admin-subtle: #7f8ea1;
  --admin-accent: #72b9f4;
  --admin-accent-hover: #91cbfb;
  --admin-surface: #151b24;
  --admin-surface-soft: #202833;
  --admin-border: #384454;
  --admin-focus: #72b9f455;
}
</style>
