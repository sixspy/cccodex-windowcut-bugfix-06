export const reconcileViewTemplate = `
<div class="card wide" v-show="tab===4">
  <h2>物化对账 · 结账灯（甲路径：厘级门禁灭灯）</h2>
  <p>
    窗内事件 {{recon.window_events}} / 金额 {{recon.window_amount}} ·
    迟到桶 {{recon.late_bucket}} · 拒收 {{recon.rejects}} ·
    金额差 <b :class="(recon.diff_amount||0)>=0.01?'late':'ok'">{{recon.diff_amount}}</b> ·
    对齐 <b :class="recon.aligned?'ok':'late'">{{recon.aligned}}</b> ·
    结账灯 <b :class="recon.lit===true?'ok':'late'">{{ recon.lit===true ? '亮' : '灭' }}</b>
    <span class="muted" v-if="recon.light_policy">（口径 {{recon.light_policy}}）</span>
  </p>
  <p class="muted">厘级门禁：abs(窗内金额 − 物化金额) ≥ 0.01 强制灭灯并同事务写差额审计，正式结论不得为真。</p>
  <table>
    <thead><tr><th>窗口</th><th>状态</th><th>窗内笔数</th><th>窗内金额</th><th>迟到</th><th>对齐</th><th>结账灯</th></tr></thead>
    <tbody>
      <tr v-for="r in reconAll" :key="r.window_id">
        <td>{{r.name}}</td>
        <td>{{r.status}}</td>
        <td>{{r.window_events}}</td>
        <td>{{r.window_amount}}</td>
        <td>{{r.late_bucket}}</td>
        <td :class="r.aligned?'ok':'late'">{{r.aligned}}</td>
        <td :class="r.lit===true?'ok':'late'">{{ r.lit===true ? '亮' : '灭' }}</td>
      </tr>
    </tbody>
  </table>
  <h2 style="margin-top:16px">差额审计（结论为真才允许亮灯）</h2>
  <table>
    <thead><tr><th>窗口</th><th>窗内金额</th><th>物化金额</th><th>差额</th><th>正式结论</th><th>人</th><th>时间</th></tr></thead>
    <tbody>
      <tr v-for="d in diffAudits" :key="d.id">
        <td>{{d.window_id}}</td>
        <td>{{d.window_amount}}</td>
        <td>{{d.materialized_amount}}</td>
        <td :class="'late'">{{d.diff_amount}}</td>
        <td :class="d.conclusion?'ok':'late'">{{d.conclusion}}</td>
        <td>{{d.actor}}</td>
        <td>{{d.created_at}}</td>
      </tr>
      <tr v-if="!diffAudits.length"><td colspan="7" class="muted">暂无差额审计（无差额灭灯场景）</td></tr>
    </tbody>
  </table>
</div>
`;
