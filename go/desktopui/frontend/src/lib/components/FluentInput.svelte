<script lang="ts">
  let {
    value = '',
    placeholder = '',
  }: {
    value?: string
    placeholder?: string
  } = $props()
</script>

<div class="fluent-input">
  <input type="text" {value} {placeholder} readonly />
</div>
