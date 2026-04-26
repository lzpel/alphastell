# bbox サブコマンド追加と STEP 単位 cm/mm 問題

## 1. 背景

`alphastell` の出力 STEP と `parastell/examples/alphastell_full/` の参照 STEP を比較する際に、各形状の軸並行バウンディングボックス (AABB) を一発で並べたい場面が出てきた。`validate` は体積比と Union 体積で形状整合を見るが、空間的な広がりが妥当かを目視で確認する手段がなかった。

## 2. `alphastell bbox` サブコマンドの追加

### 仕様
- `bbox <file1> <file2> ...` の形で複数 STEP を受け取り、ファイルごとに 1 行で AABB を出力
- 出力形式 (空白区切り): `path x0 y0 z0 x1 y1 z1 dx dy dz`
  - `(x0,y0,z0)` = AABB 最小点、`(x1,y1,z1)` = 最大点
  - `dx,dy,dz` = それぞれの差 (軸ごとの広がり)
- 内部実装は `cadrum::Compound::bounding_box() -> [DVec3; 2]` を直接呼ぶだけ

### 変更ファイル
- `src/bbox.rs` (新規): STEP を `cadrum::read_step` で読み、bbox を出力
- `src/main.rs`: `mod bbox;` 追加、`Bbox { inputs: Vec<PathBuf> }` サブコマンドの追加・dispatch

### コードの要点

```rust
// src/bbox.rs
use cadrum::Compound;

pub fn run(inputs: &[PathBuf]) -> Result<()> {
    for path in inputs {
        let solids = read_step_file(path)?;
        let [min, max] = solids.bounding_box();
        let dx = max.x - min.x;
        let dy = max.y - min.y;
        let dz = max.z - min.z;
        println!(
            "{} {} {} {} {} {} {} {} {} {}",
            path.display(),
            min.x, min.y, min.z,
            max.x, max.y, max.z,
            dx, dy, dz,
        );
    }
    Ok(())
}
```

`Compound` は `Vec<Solid>` 用にも自動実装されているので、複数 Solid を含む STEP もそのまま和集合 bbox になる。

## 3. Makefile への `bbox` ターゲット追加

`./makefile` に下記ターゲットを追加。`PARA_DIR := parastell/examples/alphastell_full` 既存変数を再利用。

```make
bbox:
	cargo run --release -- bbox $(wildcard $(PARA_DIR)/*.step)
```

## 4. 実行結果 (parastell/examples/alphastell_full の 9 STEP)

| ファイル | x0 | y0 | z0 | x1 | y1 | z1 | dx | dy | dz |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| back_wall.step      | ~0 | ~0 | -456.58 | 1515.09 | 1515.09 | 456.58 | 1515.09 | 1515.09 |  913.16 |
| breeder.step        | ~0 | ~0 | -451.58 | 1510.08 | 1510.08 | 451.58 | 1510.08 | 1510.08 |  903.16 |
| chamber.step        | ~0 | ~0 | -371.50 | 1430.03 | 1430.03 | 371.50 | 1430.03 | 1430.03 |  743.00 |
| first_wall.step     | ~0 | ~0 | -376.50 | 1435.05 | 1435.05 | 376.50 | 1435.05 | 1435.05 |  752.99 |
| magnet_set.step     | -238.44 | -238.44 | -720.96 | 1801.22 | 1801.22 | 720.96 | 2039.66 | 2039.66 | 1441.92 |
| plasma.step         | ~0 | ~0 | -360.62 | 1423.58 | 1423.58 | 360.62 | 1423.58 | 1423.58 |  721.24 |
| shield.step         | ~0 | ~0 | -506.60 | 1565.11 | 1565.11 | 506.60 | 1565.11 | 1565.11 | 1013.20 |
| sol.step            | ~0 | ~0 | -367.51 | 1426.03 | 1426.03 | 367.51 | 1426.03 | 1426.03 |  735.01 |
| vacuum_vessel.step  | ~0 | ~0 | -516.60 | 1575.12 | 1575.12 | 516.60 | 1575.12 | 1575.12 | 1033.20 |

### 観察
- 真空容器側 6 層は X≥0, Y≥0 側にしか伸びていない → **1 周期分 (1/4 セクタ)** のみ生成されていることを反映 (既知)
- `magnet_set.step` だけは X / Y も負側まで広がる → **全周分のコイル** が含まれる
- 内側ほど (chamber/plasma) bbox が小さく、外側ほど (vacuum_vessel) 大きい階層構造 — vessel 構築の物理スケールと整合

## 5. STEP の単位は cm か mm か問題

### 数値スケールから見れば「cm」
- parastell の例 `alphastell_fullcad_to_dagmc_example.py` は `scale=100.0` (m→cm)
- alphastell も `vessel --scale 100.0` (既定) で同じく cm
- 数値の妥当性: plasma の半径方向広がり ~1423 → cm 解釈で **約 14.2 m**。mm 解釈なら 1.4 m で stellarator として小さすぎる
- 中性子工学 (OpenMC, MCNP, DAGMC) は歴史的に **cm が標準単位** なので、その周辺ツール (parastell) は cm を採用

### しかし STEP ヘッダは「mm」と宣言している

```
$ grep SI_UNIT parastell/examples/alphastell_full/plasma.step
#286645 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );
```

`SI_UNIT(.MILLI.,.METRE.)` = **mm**。つまり parastell が出力する STEP は:
- 数値: cm スケール
- ヘッダ宣言: mm

の不整合状態にある。中性子工学側は `cm 前提` で動くのでヘッダは無視されて問題が顕在化しないが、汎用 CAD ビューア (FreeCAD / KiCad / SolidWorks 等) で開くと **1/10 のサイズに見える** 落とし穴。

### CAD 業界一般の慣習
| 単位 | よくある場面 |
|---|---|
| **mm** | 機械系 CAD のデファクト (SolidWorks / CATIA / NX / Onshape / FreeCAD すべて既定) |
| inch | 米国系ツール |
| m | 建築・土木・大型構造物 |
| **cm** | メインストリーム CAD ではほぼ見ない / 中性子工学界隈だけ |

「cm 単位の STEP」は CAD 一般の感覚では珍しい部類。parastell / alphastell が cm を採用しているのは中性子工学 toolchain との整合性のため。

## 6. 今後

- alphastell 側で出力する STEP のヘッダも、明示的に cm を宣言する (もしくは m / mm に統一して数値スケールも揃える) 改修を検討する余地がある
- 上流 parastell に PR を投げて修正してもらう方が筋は良いが、cad_to_dagmc / cadquery 側の事情で簡単には変えられない可能性がある
- 当面は「cm 解釈」を前提運用、bbox 出力もその前提で読む
