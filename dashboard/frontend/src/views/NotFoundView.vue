<template>
  <div class="nf-root">
    <div class="nf-content">
      <div class="nf-code">404</div>
      <h1 class="nf-title">{{ $t('not_found.title') }}</h1>
      <p class="nf-desc">{{ $t('not_found.desc') }}</p>
      <n-button type="primary" size="large" @click="$router.push('/')">
        {{ $t('not_found.back') }}
      </n-button>
    </div>
  </div>
</template>

<style scoped>
.nf-root {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 50vh;
  text-align: center;
}
.nf-content {
  max-width: 400px;
}
.nf-code {
  font-size: 96px;
  font-weight: 700;
  color: #f0b90b;
  line-height: 1;
  margin-bottom: 8px;
  font-family: 'Outfit', sans-serif;
}
.nf-title {
  font-size: 24px;
  font-weight: 600;
  margin: 0 0 8px;
  color: #e6edf3;
}
.nf-desc {
  font-size: 15px;
  color: #8b949e;
  margin: 0 0 24px;
  line-height: 1.5;
}
</style>