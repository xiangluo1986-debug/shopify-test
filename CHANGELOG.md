# 更新日志

## 2026-05-14

- Added Phase E2 settlement batch entry structure and read-only Admin visibility for future merged Shenzhen group coverage, without changing current SettlementBatch totals, CSV export, payment actions, or Shopify sync.
- Added Phase D merged Shenzhen settlement group cost summaries: group-level shipping/ordering cost entry, product-only member item rollup, cost completeness checks, enhanced group Admin detail, member inline cost status, and Shopify Order group warning without changing single-order formulas.
- Added Phase C Shopify Orders admin action for creating draft Shenzhen merged settlement groups from selected eligible orders, with strict no-package, no-settlement-batch, exact-address, status, active-group, and item-level shipping/ordering-cost guards.
- Added Phase B base models and read-only Admin display for Shenzhen merged settlement groups, keeping Shopify orders separate and leaving settlement cost formulas unchanged.

## 2026-05-12

- Shopify Order 顶部当前订单摘要新增“澳币结算金额” badge，按系统维护的 AUD/CNY 汇率将结算总成本 RMB 换算为 AUD。
- 修正 Admin / Finance 可见的深圳仓利润收入公式：全深圳仓订单会将订单级额外收入（例如运费收入）计入深圳仓收入合计；混仓订单仍不自动归属订单级额外收入，避免误算 Sydney / 其它仓收入。
- 简化 Shenzhen Warehouse 账号后台 UI：隐藏旧运费规则、旧国家默认运费、产品国家默认运费和成本历史等非日常左侧入口，收紧 Shopify Orders 右侧筛选和批量 actions，并隐藏深圳仓视图中的 Shopify Sync Dashboard 按钮。
- 第三轮简化 Shopify Sync 左侧导航：所有角色左侧只保留 Shopify Orders、Settlement Batches、Shopify Products 和 Finance Exchange Rates；同时统一 Shopify Orders 右侧筛选为结算状态、国家和订单创建时间。
- Shopify Orders 新增 Admin/Finance “提出异常订单审核”流程，可将深圳仓已确认成本、待 Admin 审核的订单退回为“异常待审核”，并强制填写异常原因。
- 新增 `exception_review` 结算状态；旧 `exception` 保留给同步异常 / 仓库位置变化异常，并显示为“同步异常待审核”。
- 异常待审核订单会记录提出人、提出时间、异常原因、深圳仓回复、回复人和回复时间。
- Shenzhen Warehouse 可在“异常待审核”状态重新编辑成本、运费、拍单成本、package 和 item 信息，并填写回复说明后重新提交 Admin 审核。
- 待支付、已提交支付、已支付或已加入结算批次的订单仍然不能退回异常审核，也不能由深圳仓继续修改成本。

## 2026-05-08

- Admin / Finance 账号新增深圳仓订单利润统计：按深圳仓商品行澳币收入扣除 2% 收款手续费，再用实时 AUD/CNY 汇率换算深圳结算成本，显示利润 AUD 和利润率；Shenzhen Warehouse 不显示该数据。
- Shopify 订单利润统计修正为只统计本地深圳仓商品行收入；订单总额与深圳仓商品行收入之间的差额不再计入深圳仓收入，避免混仓订单把 Sydney 或其它仓库收入计入深圳仓利润。
- 售后补单 / 100% off 折扣订单的利润统计改为按 Shopify 订单实收金额封顶，避免把折扣前商品行标价误算为深圳仓收入。
- Shopify 订单同步新增保存 `total_tip_received`；利润统计会把明确识别为 tip 的金额计入深圳仓收入和利润，其它订单级差额仍不计入深圳仓收入。
- 利润统计补充扣除 Shopify order note 中 PL 首行记录的澳币拍单成本；没有 PL 的线下订单不扣该项。
- PL 首行没有填写澳币金额时，利润统计按 1 美金小金额链接估算为 A$1.60 扣除。
- 利润统计收入改为只统计深圳仓商品行实际收入，并额外计入 Shopify 明确标记的 tip；订单级其它差额不再自动计入深圳仓收入。
- 当前订单摘要栏为 Admin / Finance 显示利润 AUD 和利润率，Shenzhen Warehouse 不显示这两项。
- Shopify Orders 审核流程调整为两步：深圳仓先审核并提交 Admin/Finance 审核，Admin/Finance 只能在深圳仓审核完成后审核订单并进入待结算状态。
- Shopify Order 详情页新增审核按钮：深圳仓可在维护成本后直接确认成本，Admin/Finance 只能在深圳仓确认后继续确认。
- Shopify Order 的 settlement status 改为详情页只读，避免手动跳过深圳仓审核或 Admin/Finance 审核顺序。
- Shopify Order 后台将 `cost_confirmed` 显示为“深圳仓已确认成本，待 Admin 确认”，避免和 Admin 已确认状态混淆。
- Shopify Orders 右侧 settlement status filter 隐藏“Admin 已确认”项，因为 Admin/Finance 确认后会直接进入“待支付”。
- Shopify Order 商品行在“商品行拍单成本 RMB”旁新增“拍单提示”悬浮窗口，方便审核时核对 PL note 推断信息。
- Shopify Order 详情页审核通过后会自动返回原来的 Orders 筛选列表，方便继续审核下一个订单。
- Shopify Order 详情页的“审核操作”移动到页面底部，方便核对成本明细后直接确认。
- Shopify Order 商品行数量大于等于 2 时，在订单详情页用红色加粗显示，提醒多件商品。
- Shopify Order 商品行的产品成本、商品行运费、商品行拍单成本、总成本和重量列增加醒目高亮，方便深圳仓填写和复核关键字段。
- Shopify Orders 主列表每页改为 25 条，并关闭大量订单一次性显示，减少首次打开卡顿。
- Shopify 结算流程在“待支付”和“已支付”之间新增“已提交支付，待深圳仓确认收款”状态。
- Admin / Finance 可对已加入结算批次的待支付订单或结算批次执行“提交支付”，深圳仓确认收款后才会变为已支付。
- 结算批次新增付款凭证上传字段，深圳仓确认收款时会要求对应结算批次已有付款凭证。
- Shopify Orders 列表页待支付订单结算金额统计改为按当前 package / 商品行结算公式即时计算，并新增“昨天”统计。
- Shopify Orders 待支付统计为 Admin / Finance 增加利润 AUD 和利润率汇总，Shenzhen Warehouse 不显示利润数据。
- Admin / Finance 可看到深圳仓订单低利润率提醒；当利润率低于 35% 时，系统提示本单深圳仓收款金额提高到多少 AUD 可达到 35% 和 40% 利润率，Shenzhen Warehouse 不显示该提醒。
- 利润统计汇率改为 Admin / Finance 手动维护的 AUD/CNY 汇率，不再依赖外部汇率接口；Shenzhen Warehouse 看不到汇率维护页面和利润数据。
- Shopify 订单详情页新增跟随滚动的当前订单摘要栏，滚动到商品行底部时仍可看到订单号、客户、国家、状态、深圳仓产品行数、结算总成本和 tracking number。
- 当前订单摘要栏改为浅蓝底、深色文字和蓝色边框，提升滚动时的可读性。
- 当前订单摘要栏的国家字段增加中文国家名显示，例如 AU / 澳大利亚。
- Shopify Order Packages 区域增加中文操作说明，提示先保存包裹、再给商品行选择 package，并说明包裹费用和商品行费用的适用场景。
- Shopify 订单详情页的商品行新增“产品图”悬浮预览，鼠标移到“查看图片”可查看匹配产品缩略图，减少认错产品的风险。
- 拍单成本悬浮提示优化为只解析 Shopify order note 的 PL 首行，支持 PL 后空格、空金额、多余换行备注，并根据澳币金额粗略推断小金额/大金额链接数量。
- Shenzhen Warehouse 可在订单商品行编辑产品成本，默认只影响当前订单 item。
- 新增“更新为产品默认成本”勾选项；当产品默认成本为空或 0 时，第一次填写订单商品成本会自动写入 ShopifyProduct.product_cost_rmb，已有默认成本时才需要勾选后覆盖。
- Shopify Orders 增加批量 action，可将历史订单里已填写的商品成本同步到空的产品默认成本，并记录成本历史。
- 新增 Shopify 产品成本历史记录，记录成本变更人、时间、订单、商品行、variant、旧/新 item 成本、旧/新产品默认成本以及是否覆盖默认成本。
- Shopify order note / note_attributes 已同步到本地，订单商品行“拍单成本 RMB”输入框增加 PL note 悬浮提示；第一版仅提示，不自动写入拍单成本。
- Shopify Orders 右侧 settlement status filter 现在会在每个状态后显示当前范围内的订单数量。
- Shopify Orders 主页面的 Item Count 数字增加鼠标悬浮提示，可预览该订单前 8 个深圳仓产品、数量和 Package 信息。
- Shopify Orders 主页面的结算总成本列改为“结算总成本 RMB”，成本完整时显示订单结算总额，成本未完整时显示“未完成”。
- Shenzhen Warehouse 可在 Admin/Finance 最终确认前撤回成本确认，订单会回到 pending_warehouse 以便继续修改成本。
- 已进入待支付、已支付或结算批次的订单不能撤回，Shenzhen Warehouse 也不能继续编辑 package / item 成本字段。

- Shenzhen Warehouse 账号现在可以在订单详情页新增和编辑 package，Package 删除权限仍然关闭以避免误删历史结算结构。
- 深圳仓订单详情顶部隐藏 tracking_url，不再显示 kidstoylover / ParcelPanel 店铺 tracking 链接，改为显示 tracking number、carrier、履约状态和同步时间等物流摘要。
- 包裹级结算支持混合模式：未分配包裹的单产品/历史订单继续使用商品行运费和拍单成本，有包裹的商品按包裹费用汇总。
- 包裹级结算改为直接使用包裹运费和包裹拍单成本计算订单总成本，不再把包裹费用分摊写入商品行。
- 订单详情页增加包裹成本汇总、深圳仓当前结算总成本汇总，并在包裹费用尚未分摊到商品行时显示提示。

- 订单详情页保存不再因商品行产品成本、运费或拍单成本为空而阻止保存，成本完整性改在结算动作前校验。
- 调整包裹创建流程：订单商品行保存时只强制产品成本，运费/拍单成本完整性改在成本确认、加入结算批次和 CSV 导出前校验。
- 包裹级结算页面简化包裹填写字段，并允许已选择有效包裹费用的商品行先保存后再执行包裹分摊。
- 新增包裹级结算，支持一个订单多个包裹、包裹运费和拍单成本分摊到包裹内深圳仓产品行，CSV 增加包裹信息列。
- Shopify 自动订单同步从每 30 分钟扫描 60 天改为扫描最近 3 天，并新增同步锁、同步状态记录和 dashboard 状态显示。
- 手动 Shopify 订单同步支持最近 3/7/30/60 天选项，产品同步错过每日窗口后可自动补跑。
- 结算 ERP 订单商品行的产品成本、运费、拍单成本增加星号提示和保存校验，并优化字段顺序与输入框宽度。
- 深圳仓订单商品行的拍单成本改为结算减项，`total_cost_rmb = 产品成本 + 运费 - 拍单成本`，CSV 导出列名同步改为 ordering cost。
- 历史订单商品行支持从匹配产品临时显示产品成本、重量、尺寸、体积重量等资料。
- 新增批量回填 action，可将匹配产品资料写入历史订单商品行。
- 历史订单商品行回填只填空值，不覆盖人工输入值。
- 订单产品行支持直接编辑重量、长宽高、体积重量、手续费等资料。
- 订单产品行保存后，可将产品成本、重量、长宽高、体积重量同步回对应 ShopifyProduct。
- 后续同产品订单可自动带出已维护的产品成本和尺寸资料。
- Shenzhen 仓运费默认值改为产品 + 国家维度。
- 在订单产品行输入 locked shipping cost 后，可保存为该 Shopify variant 发往该国家的默认运费。
- 后续同 variant 同国家的深圳仓订单会自动带出默认运费。
- 结算不再按订单总运费平均分摊，每个产品行使用自己的 locked shipping cost。
- Shenzhen 仓国际运费改为人工输入，不再按重量、体积或 ShippingCostRule 自动计算。
- 支持将订单运费保存为对应国家的默认运费。
- 后续同国家深圳仓订单可在未填写运费时自动使用国家默认运费。
- 结算重算继续只计算 Shenzhen 仓产品行，混仓订单中的 Sydney / NULL 产品行不参与结算。
- 结算 CSV 和批次金额继续使用 item 级 locked shipping / total cost 字段。

## 2026-05-07

- 工单后台支持通过 ID 精确搜索工单。
- 新增工单置顶和取消置顶功能。
- 已结束工单会自动取消置顶。
- 置顶工单会优先显示在工单列表前面。
