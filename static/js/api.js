// ═══ API 请求封装（api.js）═══
    function _apiHeaders(headers = {}) {
      if (_apiKey) headers['X-API-Key'] = _apiKey;
      return headers;
    }
    async function _apiFetch(url, opts = {}) {
      opts.headers = Object.assign(opts.headers || {}, _apiHeaders());
      const r = await fetch(url, opts);
      if (r.status === 401 && !localStorage.getItem('api_key')) {
        const key = prompt('请输入 API Key：');
        if (key) { localStorage.setItem('api_key', key); location.reload(); }
      }
      return r;
    }

// ─── 命名空间挂载：把本模块声明式函数挂到 TuanboApp.api 做索引 ───
Object.assign(TuanboApp.api, {
  _apiHeaders: _apiHeaders,
  _apiFetch: _apiFetch,
});
