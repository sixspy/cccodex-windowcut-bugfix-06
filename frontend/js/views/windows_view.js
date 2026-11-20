/** 业务窗页签模板片段 */
export const windowsViewTemplate = `
<div class="card wide" v-show="tab===0">
  <h2>窗口条带</h2>
  <p class="muted">关窗占窗锁；点灯占灯锁 light:窗，后到只记争用。结账灯走厘级门禁：金额差 ≥ 0.01 强制灭灯。</p>
  <table>
    <thead><tr><th>窗口</th><th>世代</th><th>开启</th><th>关闭</th><th>状态</th><th>结账灯</th><th>操作</th></tr></thead>
    <tbody>
      <tr v-for="w in windows" :key="w.id">
        <td>{{w.name}}</td>
        <td>{{w.generation}}</td>
        <td>{{w.open_at}}</td>
        <td>{{w.close_at}}</td>
        <td>{{w.status}}</td>
        <td><span :class="lightOf(w.id)===true?'ok':'late'">{{ lightOf(w.id)===true ? '亮' : '灭' }}</span></td>
        <td>
          <button class="ghost" @click="closeWin(w.id)">关窗</button>
          <button class="ghost" @click="materialize(w.id)">物化</button>
          <button class="ghost" @click="checkoutLight(w.id)">结账灯</button>
          <button class="ghost" @click="loadRecon(w.id)">对账</button>
          <button class="ghost" @click="reopenStub(w.id)">重开空桩</button>
        </td>
      </tr>
    </tbody>
  </table>
  <div class="err">{{actionErr}}</div>
</div>
`;
