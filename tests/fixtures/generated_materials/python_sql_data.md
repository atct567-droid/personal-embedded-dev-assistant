# Python SQL 与销售 JSON 数据（合成测试摘要）

## student 表

示例创建 student 表，字段包括 id、name、age 和 gender。插入语句可以一次插入多行记录；id 用于区分学生，age 保存年龄，gender 保存性别文本。

## 销售 JSON

销售数据按行保存为 JSON，每行包含 date、order_id、money 和 province。读取时应逐行解析 JSON；统计省份销售额时按 province 分组并累加 money，而不是把 order_id 当作金额。
