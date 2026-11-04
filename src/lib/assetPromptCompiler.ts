import type {
  AssetItem,
  AssetKind,
  AssetStandardSettings,
  AssetVisualStandard,
  CostumeEra,
} from "../types";
import {
  COSTUME_ERA_OPTIONS,
  isCollectiveCharacter,
  VISUAL_STANDARD_OPTIONS,
} from "./assetStandards";

export interface CompiledAssetPrompt {
  prompt: string;
  warnings: string[];
  standardLabel: string;
  eraLabel: string | null;
}

const LIVE_ACTION_CHARACTER = `【四宫格比例与边界】
9:16竖版2×2四宫格，上排约42%、下排约58%，左右各约50%，仅保留极窄分隔线或自然拼接。上排头肩充分填满单格；下排不得压缩或裁切脚部。

【左上｜放大正面1寸证件照式肖像】
正面端正，双肩平行镜头，直视镜头。头顶上方仅留3%—6%，下缘裁至锁骨下方或上胸；头肩占单格85%—92%，面部占55%—65%。完整展示脸型、五官、皮肤纹理、发际线、发型、耳饰、项链和领口。镜头与眼睛等高，中长焦透视，不仰拍、不俯拍、不遮脸。

【右上｜放大标准90度侧面肖像】
身体与面部均为标准90度侧面，视线平视画面外；与左上人物大小、裁切、眼位和镜头距离完全一致。清楚展示额头、眉骨、鼻梁、鼻尖、嘴唇、下颌、颈部、耳朵和发型侧轮廓。不得变成四分之三侧脸，不得看镜头。

【左下｜不露脸正面服装全身】
身体正对镜头自然站立，双臂下垂，双腿双脚完整入镜。画面主动裁掉整个头部与面部，上边缘严格停在锁骨上方或颈部以下；不得出现眼、鼻、嘴、下巴或完整脸部。展示真实身高比例、肩颈、胸腰臀、四肢、服装正面版型、腰线、面料垂坠、裙摆或裤装、开衩和鞋履；不扭胯。

【右下｜标准背面完整全身】
完全背对镜头自然站立，头部、发型背面、双肩、肩胛、腰部、臀腿、下摆和双脚完整入镜；身高与左下严格一致。不得回头，不得出现正脸或明显侧脸。

【一致性与皮肤】
四格必须是同一人物、同一脸、骨相、年龄、肤色、身高、肩宽、体型、发际线、发色、服装、鞋履、配饰和识别锚点。真实皮肤保留自然毛孔、细小绒毛、轻微肤色不均、软组织纹理、眼下细纹和符合年龄的少量瑕疵；拒绝塑料皮、蜡像皮、瓷娃娃皮和商业磨皮。

【摄影与背景】
纯浅灰或中性灰无影棚背景，不出现家具和环境道具。专业柔光，主光柔和、辅光均匀、轻微轮廓光；四区曝光与白平衡一致。照片级真人摄影，真实发丝、皮肤、布料纤维与褶皱，中长焦透视，8K高清。

【限制与反向】
不得添加标题、姓名、说明、表格、数字、尺寸线、标签、Logo、水印、边框或其他人物。禁止卡通、动漫、插画、二次元、CG建模、3D渲染、游戏角色、四张不同人物、换脸换装、多人、肢体畸形、广角畸变、左下露脸、右下回头、复杂背景和文字。`;

const LIVE_ACTION_SCENE = `【16:9场景五视图】
顶部居中使用粗体中文大字“【场景名称】”，下方写“场景资产设定图”。主体为同一场景的五个清晰区域：正视图、反视图、左视图、右视图与顶视图。

【左上｜正视图】正对主要入口或视觉面，完整展示纵深、家具、墙面、门窗、地面和顶部结构，不得出现人物。
【右上｜反视图】从完全相反方向观察，完整展示背面结构、入口反向关系、家具背面和通道，不得出现人物。
【左下｜左视图】从左侧标准90度观察，展示左墙、侧面家具、门窗、宽度和纵深，不得出现人物。
【中下｜右视图】从右侧标准90度观察，展示右墙、侧面家具、门窗、宽度和纵深，不得出现人物。
【右下｜顶视图线稿】必须是清晰黑白线稿平面图，不做写实渲染。标注总长宽、区域尺寸、门窗柱子台阶屏风床榻桌椅柜架灯具与固定陈设位置、家具长宽高、通道宽度和关键道具尺寸。

【质感与一致性】
影视级场景美术设计，真实空间比例、建筑逻辑、家具尺度和材质。四个透视图统一光向、曝光、色温和镜头高度。墙地、木石、金属、织物、玻璃与纸张真实可信，保留使用痕迹、磨损、灰尘和生活痕迹。五视图必须来自同一场景，门窗、家具、入口、通道和固定陈设不可漂移。

【限制】
只允许顶部标题、五个视图小标签与顶视图必要尺寸文字。禁止人物、动物、手部、人体局部、游戏场景感、卡通化、错误透视、比例失真、单独道具展示、角色设定、分镜、电影剧照、Logo、水印和乱码；顶视图不得做成照片。`;

const LIVE_ACTION_PROP = `【纯物品9:16四宫格】
真人写实电影道具摄影。画面中禁止任何人物、角色、手、脚或人体部位。2×2上小下大布局，上排约42%为两个不同局部细节，下排约58%为两个完整不同角度；左右各约50%。

【左上｜细节特写一】放大关键部件、结构、接口、开关、纹样、雕刻、镶嵌、连接或表面工艺。
【右上｜细节特写二】展示另一处关键细节，不得重复左上，不得放入缩小的完整道具。
【左下｜完整主视角】用正面或主要45度完整展示主体、准确比例、核心造型，不得裁切关键结构。
【右下｜完整另一角度】用侧面、背面或另一45度完整展示三维结构，不得重复左下。

【一致性与材质】
四区必须是同一道具，轮廓、尺寸、结构、材质、表面处理、纹样、颜色、磨损、接口与锚点完全一致。主体材质、辅助材质、工艺、反光/粗糙、纹理和使用痕迹真实可辨。纯白背景，无多余遮挡。

【限制】
禁止人物、人手、人体部位、四个不同道具、结构漂移、材质变化、上排完整道具、下排裁切、角度重复、文字、说明、数字、标签、Logo、水印和边框。`;

const GUOFENG_3D_CHARACTER = `国风3D动画风格，中华传统美学意蕴，次表面散射（SSS）细腻肤质，PBR物理材质强调布料与金属质感，3D数字资产，电影级动态光影，8K超高清，纯白背景。

9:16竖版2×2四宫格，上排约42%、下排约58%。左上放大正面证件照式头肩，右上同尺寸标准90度侧面头肩；左下主动裁掉整个头部的正面服装全身，右下头脚完整的背面全身。四区必须是同一角色，身份、脸型、五官、肤色、年龄、身材、发型、服装、鞋履与配饰高度统一。中长焦透视，不得广角、换脸换装、裁脚、增加标题标签、Logo或水印。`;

const GUOFENG_3D_SCENE = `国风3D动画场景，中华传统美学意蕴，意境写实，虚幻引擎5（UE5）构建，体积光（Volumetric Light）与全局照明（GI），电影级光影衰减。画面中禁止任何人物、角色或人体部位。

16:9横版场景资产板：中央展示完整全景、布局、建筑结构与氛围；上方展示正面、侧面、俯视、仰视；左侧展示白天、黄昏、夜晚或晴、阴、雨状态；底部展示建筑节点、关键陈设、材质与工艺；右侧展示主色、辅助色和点缀色。所有分区必须来自同一个三维场景，门窗、梁柱、入口、家具、道路、地形和固定陈设不可漂移。禁止人物、不同场景拼接、错误透视、游戏UI、Logo、水印和乱码。`;

const GUOFENG_3D_PROP = `国风3D动画道具，中华传统美学意蕴，虚幻引擎5（UE5）渲染，光线追踪（Ray Tracing）强化金属与物理质感，PBR材质，8K超高清，电影级布光。禁止人物、角色、人手和人体部位。

16:9横版道具资产板：中央展示完整主体、准确比例和核心造型；上方展示正、侧、背、俯、仰与45度角；左侧展示真实尺寸、闭合/开启、展开/收纳和结构拆解；底部展示结构、纹样、磨损、接口、开关和工艺；右侧展示主体材质、辅助材质、表面处理和标准色卡。所有视图必须是同一道具，轮廓、尺寸、结构、材质、纹样、颜色和磨损一致。纯白背景；禁止人物、人手、Logo、水印和乱码。`;

const HANDPAINTED_STYLE = `高品质手绘三渲二动画资产设定图。零号造型锁优先：明显非真人的中度动画化比例、几何化形体平面、清晰夸张剪影与概括细节；完整可信的三维结构，Hand-painted Texture手绘覆盖感，2—3块图形化明暗，软硬边有层级，深灰/深棕变粗细外轮廓，局部断线与色线。单一主光方向并保留低强度基础明度，中低饱和基础色、中等至偏强明度对比、1—2个识别色，可见宽笔触与色块叠压。非真人摄影，非写实概念原画，非普通PBR CG，非纯二维立绘。`;

const HANDPAINTED_CHARACTER = `${HANDPAINTED_STYLE}

【9:16角色四宫格】2×2上小下大，上排42%、下排58%。左上放大正面头肩，右上同尺寸标准90度侧面头肩；左下主动裁掉头部的不露脸正面服装全身；右下头脚完整的背面全身。采用70—100mm中长焦。

【造型与材质】角色可绑定，但头颅、眼眶、颧骨、鼻梁、下颌、肩线、手脚与服装剪影必须主动设计。面部以几何平面和3—5个大面积冷暖色区塑形，不表现毛孔、皮肤透明感、湿润嘴唇或真人SSS。头发由少量大型雕塑感发束组成，禁止逐根发丝。服装以大裁片、大褶皱和清晰层级为主，用宽笔触、块状高光、边缘干刷和概括磨损区分材质。

【一致性与背景】四格同一脸、骨相、年龄、体型、发束、服装、材质、纹样、磨损和锚点。纯浅灰或中性灰手绘色卡背景，一个主光方向，四格色彩、曝光、阴影级数与高光逻辑统一。

【反向】禁止真人照片、真人五官比例、扫描头模、毛孔、真实SSS、逐根发丝、PBR、光追、电影剧照、写实概念图、加描边真人、普通写实CG、纯二维立绘、均匀细描边、纯黑轮廓、连续渐变、多主光、HDRI、塑料感、蜡像感、低模、盲盒、换脸换装、左下露脸、右下回头、软件界面、文字、Logo和水印。`;

const HANDPAINTED_SCENE = `${HANDPAINTED_STYLE}

【16:9场景五视图】顶部为“【场景名称】”和“3渲2场景资产设定图”。主体为同一场景的正视、反视、左视、右视和黑白线稿顶视平面图。透视图采用50—70mm或近正交透视，不用广角。

【造型、材质与光影】建筑、家具和地形先做动画化形体设计，门窗、梁柱、屋檐与轮廓允许适度夸张和不对称。木纹、墙皮、砖缝、锈蚀与污渍用宽笔触、色块叠压和局部干刷概括，禁止照片贴图。四个透视图共用一个主光，2—3个图形明暗块，中低饱和但保持中等至偏强对比与1—2个识别色。

【顶视与一致性】顶视图标注长宽、区域、门窗柱子台阶、家具、灯具、固定陈设、通道和关键道具尺寸。五视图必须来自同一三维场景，建筑、门窗、家具、材质、磨损和通道严格对应。

【反向】禁止实景摄影、写实建筑可视化、写实概念图、普通写实游戏场景、照片贴图、扫描材质、PBR、光追、全局灰脏、多主光、HDRI、浓雾、广角鱼眼、五个不同场景、错误顶视图、人物、动物、手、软件界面、乱码、Logo和水印。`;

const HANDPAINTED_PROP = `${HANDPAINTED_STYLE}

【纯物品9:16四宫格】禁止人物、角色、手、脚和人体部位。上排42%为两个不同局部特写，下排58%为两个完整不同角度；左下正面或主要45度，右下侧面、背面或另一45度，关键结构不得裁切。

【结构与材质】道具具有清晰厚度、重量、受力、连接件、铰链、扣合、握持、开关、装填、展开或收纳逻辑。关键部件比例可夸张，小零件概括。金属、木、皮革、陶瓷和玻璃用块状高光、颜色偏移、边缘干刷与少量纹理区分，禁止照片级反射、扫描纹理和密集微划痕。纯白、浅灰或中性灰手绘色卡背景，一个主光，70—100mm中长焦。

【一致性与反向】四区同一道具，轮廓、比例、厚度、结构、接口、材质、纹样、颜色、磨损、挂件和锚点一致。禁止产品摄影、写实PBR、光追、连续渐变、纯黑线、工业CAD、低模、盲盒、塑料感、无厚度、四个不同道具、上排完整道具、下排裁切、角度重复、软件界面、文字、Logo和水印。`;

const DARK_VISUAL_LOCK = `Dark medieval epic television aesthetic, cold blue-gray palette, desaturated earth tones, steel gray and muddy brown, firelit orange-red accents, overcast natural light, torchlit practical lighting, low-key high-contrast shadows, volumetric light through smoke and dust, gritty medieval realism, dense cinematic grain, monumental scale, brutal fatalism and political tension. Live-action feature film production still, photographed on real locations and physically built sets, practical costumes, props, prosthetic makeup and animatronics, natural human skin texture, tactile stone, wood, metal, leather and textile surfaces, physically plausible wear, weight and weathering, cinematic lens behavior, natural depth of field and exposure, invisible visual effects integration only where physically necessary, absolutely no 3D render, CGI look, game-engine image, digital illustration, plastic skin or synthetic materials.`;

const DARK_CHARACTER = `${DARK_VISUAL_LOCK}

【16:9真人角色定妆与镜头测试板】中央为同一真人演员当前形态的完整3/4全身；上方为正面、标准90度侧面和背面；左侧为正面/3/4/侧面头肩皮肤特写与克制表情组；底部为实体服装、鞋履或蹄部、甲胄、武器、纹章和种族妆效；右侧为身高、体型轮廓、形态关联轮廓和低饱和色板。全部分区保持同一演员、年龄、妆发、形态和磨损状态。

【角色与种族】写明人族/非人种族、本体/完全人形/半人形、年龄、身高、地域、势力、职业和阶层。人类锁定西方白人骨相并以年龄、阶层、地域、营养和风霜制造差异。非人结构优先实体特效化妆、假体或机械装置；跨形态共享瞳色、伤疤、纹章、主色、魔法来源与3—5个身份锚点。

【皮肤、服装与摄影】保留毛孔、细纹、绒毛、轻微瑕疵、肤色不均、风霜和旧伤，不磨皮。实体服装按内层、中层、外层、鞋履、甲胄、披风、腰带、武器和纹章构成。阴天冷光或可见火把/窗缝实景光，85mm头肩与50mm全身电影镜头，自然景深和颗粒。

【禁止】3D、CG、游戏引擎、数字插画、概念图、非西方人类族裔、现代偶像脸、动漫、Q版、塑料皮、无毛孔磨皮、换演员换装、随机发光、干净cosplay、现代/东方/科幻元素、乱码和水印。`;

const DARK_SCENE = `${DARK_VISUAL_LOCK}

【16:9实景勘景与实体搭景板】中央为无人实景/实体搭建场景主镜头；上方为入口正视、反向、左侧、右侧与航拍/高机位；左侧为同一场地的阴天、火光、风雪或战后状态；底部为墙体、门窗、屋顶、家具、道路、纹章、排水、防御与材料微距；右侧为尺寸、动线、实体材质样本和低饱和色板。所有角度结构和陈设一致。

【建筑与空间】写明地域、气候、势力、社会等级、功能与状态；明确建筑主体系、承重、门窗、屋顶、楼梯/坡道、排水、供暖、照明、防御和逃生。入口、主轴、动线、家具、仓储、武器架、马厩、炉火、祭坛、工坊或魔法隔离区必须服务功能。

【材质、天气与摄影】粗石孔隙、灰浆缝、湿木裂口、锻铁锤痕、旧钢氧化、毛毡纤维、皮革油脂、陶土缺口、积雪、泥水、苔藓、烟灰和战损真实可触。24—35mm实景摄影；阴天冷光、窗缝光、火把、烛火、壁炉或熔炉均为可见实景光。

【禁止】3D、CG建筑、游戏引擎、数字绘景、概念图、人物、人手、人影、主题乐园式干净、现代城市、东方建筑、蒸汽朋克、科幻结构、无功能奇观、错误尺度、结构漂移和乱码。`;

const DARK_PROP = `${DARK_VISUAL_LOCK}

【16:9电影道具实物测试板】中央为道具在冷灰石台或旧木台上的完整3/4实拍；上方为正、侧、背、俯、仰；左侧为真实尺寸、闭合/开启、拆解与工作结构；底部为刃口、护手、接口、符文、纹章、宝石、缝线、磨损、氧化、指纹和修补微距；右侧为实体材料样本、表面处理与低饱和色板。禁止人物、人手、人体部位与人形支架。

【结构、功能与魔法】写明轮廓、部件、握持、配重、刃口、护手、机关、开合、锁扣、接口、容积、拆卸、维修和收纳。魔法必须说明能源/祭品/符文/晶体/圣物来源、激活、代价、反馈、冷却与失效，不得无理由全身发光。

【材料与摄影】锻铁、旧钢、青铜、银、木、皮革、骨角、石、陶、玻璃、宝石、羊皮纸与织物具有可触摸差异；呈现孔隙、木纹、锤痕、倒角、接缝、铆钉、雕刻、镶嵌、氧化、指纹、油脂、泥污和修补。70—100mm实拍，阴天冷光与火把实景光。

【禁止】3D、CG道具、游戏图标、数字插画、材质球、塑料金属、完美无磨损、人物、人手、人体部位、现代枪械、东方兵器、蒸汽朋克、科幻机械、随机尖刺、无功能装饰、悬浮、比例不明、结构漂移和乱码。`;

const VICTORIAN_VISUAL_LOCK = `Dark Victorian Gothic period drama aesthetic set in 19th-century Britain, historically accurate 1837–1901 clothing, architecture, interiors, transportation and props, soot-black and fog-gray palette, desaturated bottle green, oxblood, navy, mahogany brown and tarnished brass, gaslight amber and candlelit highlights, overcast London daylight, coal-smoke haze, wet cobblestones, low-key high-contrast practical lighting, volumetric light through fog and dust, gritty industrial realism, dense cinematic grain, class tension, scientific ambition and occult dread. Live-action Victorian Gothic feature film production still, photographed on real British locations and physically built period sets, historically accurate practical costumes, uniforms, props, carriages, railway equipment and interiors, natural human skin texture and tactile period materials, absolutely no 3D render, CGI look, game-engine image, digital illustration, plastic skin, synthetic modern fabrics or anachronistic technology.`;

const VICTORIAN_CHARACTER = `${VICTORIAN_VISUAL_LOCK}

【9:16维多利亚角色四宫格】2×2上小下大，上排42%：左上放大正面1寸式头肩、右上同尺寸标准90度侧面头肩；下排58%：左下主动裁掉整个头部的正面服装全身、右下头脚完整的标准背面全身。四格为同一人、同一具体年份、同一套服装、配饰与形态。

【年代、身份与形态】写明1837—1901具体年份或早/中/晚期、英国地域、机构/家族、职业与阶层。人类默认英国白人骨相；非人形态需适配维多利亚服装。跨形态共享瞳色、伤疤、机构标识、主色、魔法来源、年份与3—5个身份锚点。

【服装】按年份写明贴身层、中层、外层、帽饰、手套、鞋靴、披肩/雨披/大衣、腰带口袋和职业器物。女装区分早期收腰长裙、中期裙撑、晚期巴斯尔/羊腿袖；男装使用衬衫、高领、领巾/领结、马甲和对应礼服外套。禁止现代拉链、现代西装与错误年代轮廓。

【皮肤、摄影与背景】真实皮肤保留毛孔、绒毛、肤色不均、细纹、雀斑、痘印、煤灰与雨水，不磨皮。纯浅灰或中性灰无影棚，专业柔光，不出现街道、烟雾、家具或场景背景；中长焦，四格曝光与白平衡一致。

【禁止】标题、姓名、说明、表格、数字、标签、Logo、水印、其他人物、3D、CG、游戏引擎、数字插画、非西方人类族裔、现代偶像脸、动漫、塑料皮、现代服装和技术、齿轮堆叠式蒸汽朋克、换脸换装、广角畸变和裁脚。`;

const VICTORIAN_SCENE = `${VICTORIAN_VISUAL_LOCK}

【16:9维多利亚场景五视图】顶部为“【场景名称】”和“场景资产设定图”。主体为同一无人实景/实体搭景的正视、反视、左视、右视与黑白线稿顶视图。年份、建筑结构、煤气/供暖/排水设施、尺寸、家具、门窗与空间比例必须一致。

【年代、建筑与设施】写明1837—1901具体年份或早/中/晚期，选择乔治亚遗留、哥特复兴、意大利式、新古典、第二帝国、安妮女王复兴、都铎复兴、艺术与工艺或工业红砖等体系。明确砖石承重、灰石立面、铸铁柱、熟铁/玻璃屋顶、木桁架、凸窗、山墙、烟囱、壁炉、煤窖、仆役楼梯、锅炉房、煤气管、给排水、通风、照明、消防和逃生。

【材质、陈设与光线】使用红砖、灰石、抹灰、木饰面、铸铁、黄铜、玻璃、瓷砖、壁纸、地毯与木地板等符合年份的真实材质；家具器械符合阶层与功能。英国阴天、窗光、煤气灯、油灯、烛火、壁炉、煤炉或符合晚期年份的电弧/电灯必须有可见来源与管线。

【顶视与一致性】顶视技术线稿标注总长宽、区域、门窗、壁炉烟道、柱子、楼梯、仆役通道、家具设备、通道、煤气管线与固定设施尺寸。五视图不得增删房间、通道、家具、机器或设施。

【禁止】除标题、视图标签和必要尺寸外不得增加文字。禁止3D、CG、游戏引擎、数字绘景、人物、人手、人影、20/21世纪城市、泛中世纪城堡、东方建筑、科幻结构、齿轮堆叠式蒸汽朋克、错误年份、错误尺度、结构漂移和乱码。`;

const VICTORIAN_PROP = `${VICTORIAN_VISUAL_LOCK}

【16:9维多利亚道具实物测试板】中央为道具在深色木台、皮革桌垫、实验台或铸铁工作台上的完整3/4实拍；上方正、侧、背、俯、仰；左侧真实尺寸、闭合/开启、拆解与工作结构；底部枪机、转轮、刃口、接口、镜片、阀门、导线、铭牌、煤灰、氧化、指纹与修补；右侧实体材料样本、表面处理和低饱和色板。禁止人物、人手、人体部位与人形支架。

【年份、结构与功能】写明1837—1901具体年份、机构/家族、用途、尺寸重量与制造来源。描述握持/安装、配重、击发与装填、枪机/转轮/弹仓、镜片、阀门、活塞、导线、原电池、传动、开合、接口、拆卸、维修与收纳；技术必须符合年份。

【材料与摄影】发蓝钢、枪金属、铸铁、熟铁、黄铜、铜、镍银、银、木、皮革、骨角、瓷器、玻璃、宝石、符合年份的硬橡胶、纸和织物必须真实可触；呈现车削、铸造、锤痕、接缝、铆钉、螺钉、氧化、煤灰、枪油、指纹、雨渍与修补。70—100mm实拍，使用阴天窗光或煤气灯等实用光。

【禁止】3D、CG、游戏图标、塑料金属、完美无磨损、人物、人手、现代自动枪械、现代弹匣和光学瞄具、LED、20/21世纪电子设备、东方兵器、泛中世纪武器、科幻机械、齿轮堆叠式蒸汽朋克、错误年份、悬浮、结构漂移和乱码。`;

const TEMPLATE_BY_STANDARD: Record<AssetVisualStandard, Record<AssetKind, string>> = {
  "live-action": { character: LIVE_ACTION_CHARACTER, scene: LIVE_ACTION_SCENE, prop: LIVE_ACTION_PROP },
  "guofeng-3d": { character: GUOFENG_3D_CHARACTER, scene: GUOFENG_3D_SCENE, prop: GUOFENG_3D_PROP },
  "handpainted-3d2d": { character: HANDPAINTED_CHARACTER, scene: HANDPAINTED_SCENE, prop: HANDPAINTED_PROP },
  "western-dark-medieval": { character: DARK_CHARACTER, scene: DARK_SCENE, prop: DARK_PROP },
  "victorian-gothic": { character: VICTORIAN_CHARACTER, scene: VICTORIAN_SCENE, prop: VICTORIAN_PROP },
};

const DETAILED_ERA_RULES: Partial<Record<CostumeEra, string>> = {
  han: "汉代男性服饰：按身份选择深衣（曲裾或直裾）等合适形制，交领右衽、宽袖；冠制、印绶、面料和配色服从阶级。禁止唐代圆领袍与幞头、明代补子与网巾。",
  tang: "唐代男性服饰：按身份选择圆领袍等形制，幞头、玉带銙数、鱼袋、品色与面料服从阶级。禁止明代补子、网巾与乌纱帽。",
  song: "宋代男性服饰：按身份选择圆领袍、直裰等形制，整体清雅克制，幞头/巾帻、印绶、品色与面料服从阶级。禁止明代补子、网巾与马面裙。",
  ming: "明代男性服饰：便服与朝服严格区分；按身份选择圆领袍、补服等形制，乌纱帽、补子、玉带銙只在官阶成立时使用，男性可按身份使用网巾。禁止清代旗袍与马蹄袖。",
};

const MING_FEMALE_RULE = "明代女性服饰：按身份与场合选择直领大襟（交领）短袄或对襟衫袄，下配马面裙；可按身份罩方领对襟比甲。皇室与高等级女性可使用暗花、织金或妆花丝织物，侍女与平民降低纹样密度、材质与饱和度。发式盘髻并按身份配置簪钗；凤冠、霞帔等礼服组件只在符合身份的正式礼仪场合使用，日常造型不得滥用。禁止清代旗装、马蹄袖、晚清多重滚边、西式束腰与现代影楼古装。";

const GROUP_STYLE: Record<AssetVisualStandard, string> = {
  "live-action": "真人写实电影选角照，真实中国演员，真实皮肤、发丝、布料纤维与自然体型，克制的影视棚拍光线",
  "guofeng-3d": "高品质国风3D动画群像，统一的电影级PBR材质、皮肤SSS与中华传统审美，拒绝塑料玩具感",
  "handpainted-3d2d": "手绘3渲2群像，统一的分块明暗、手绘纹理、选择性描边与非照片级造型语言",
  "western-dark-medieval": "西方暗黑中世纪真人电影群像，真实演员、做旧材质、冷峻低饱和实拍质感",
  "victorian-gothic": "维多利亚时代暗黑真人电影群像，真实演员、符合年代的剪裁与材料、克制哥特氛围",
};

function collectiveProfile(name: string) {
  if (name.endsWith("萧府护卫们")) {
    return {
      count: "6—8人",
      gender: "全部为男性：6—8名成年男性，女性0人",
      identity: "20—45岁的明代武将府邸家兵与护卫，身高、年龄、体型、脸型、肤色与风霜程度各不相同",
      wardrobe: "深青、墨黑、灰褐等低饱和窄袖袍服、护腕、皮革腰带与便于行动的靴履；每人的层次、旧化、束带、护腕和小配件不同，但同属萧府体系；兵器收鞘，不遮挡全身",
    };
  }
  if (name.endsWith("萧府婆子侍女")) {
    return {
      count: "6—8人",
      gender: "全部为女性：2—3名中老年婆子，加4—5名年轻侍女，男性0人",
      identity: "明代将军府内宅仆役，年龄、身高、体型、脸型、肤色与神态各异，婆子稳重老练，侍女年轻利落",
      wardrobe: "婆子与侍女分别穿符合身份的明代衫袄、比甲与马面裙，材质朴素、纹样克制；颜色、领型、袖口、腰间小物与发髻各异，但保持同一府邸的服装体系",
    };
  }
  if (name.endsWith("暗影卫众")) {
    return {
      count: "6—8人",
      gender: "全部为男性：6—8名成年男性，女性0人",
      identity: "训练有素的明代秘密护卫，年龄、身高、体型与脸型各异，神情警觉克制，不得复制同一张脸",
      wardrobe: "黑、炭灰、深靛色的明代行动装束，窄袖、护腕、束带、软靴与少量功能配件各不相同；统一隐秘职能但绝非整齐复制的制服克隆人",
    };
  }
  if (name === "众人" || name.endsWith("众人")) {
    return {
      count: "8—10人",
      gender: "男性4—5人、女性4—5人，男女总数必须为8—10人",
      identity: "明代宅邸或庭院中的背景群演，覆盖青年、中年和少量年长者，身份层级、身高、体型、脸型与神态各不相同",
      wardrobe: "按男女与身份分别穿明代日常服饰，材料、颜色、旧化程度、发式和小配件各异；不得出现清代旗装、马蹄袖或现代影楼古装",
    };
  }
  return {
    count: "6—8人",
    gender: "男性3—4人、女性3—4人，男女总数必须为6—8人",
    identity: "同一时代与职能下的背景群演，年龄、身高、体型、脸型、肤色、发型和神态各不相同",
    wardrobe: "服装款式、颜色、材质、旧化、配饰与发式各异，但保持同一时代、阶层与制作画风",
  };
}

function compileCollectivePrompt(
  item: AssetItem,
  settings: AssetStandardSettings,
  standardLabel: string,
): CompiledAssetPrompt {
  const profile = collectiveProfile(item.name);
  const era = COSTUME_ERA_OPTIONS.find((option) => option.id === settings.costumeEra)
    ?? COSTUME_ERA_OPTIONS[0];
  const compatibleWithChineseCostume = VISUAL_STANDARD_OPTIONS.find(
    (option) => option.id === settings.visualStandard,
  )?.compatibleWithChineseCostume;
  const mingCostumeRule = profile.gender.includes("女性0人")
    ? "男性束发并按身份使用网巾或合适巾帽，服装材料、纹样与配饰服从其职能和身份。"
    : profile.gender.includes("男性0人")
      ? "女性使用明代盘髻、衫袄、比甲与马面裙体系，服装材料、纹样与配饰服从其职能和身份。"
      : "男性束发并按身份使用网巾或合适巾帽；女性使用明代盘髻、衫袄、比甲与马面裙体系；所有人的材料、纹样与配饰服从身份。";
  const eraRule = compatibleWithChineseCostume && settings.costumeEra === "ming"
    ? `时代严格锁定明代。${mingCostumeRule}禁止清代旗装、马蹄袖、晚清滚边、西式束腰和现代影楼古装。`
    : compatibleWithChineseCostume && settings.costumeEra !== "auto"
      ? `时代严格锁定${era.label}代，所有男女服饰、发式、材料与配饰必须符合该朝代和身份，不混入其他时代标志。`
      : compatibleWithChineseCostume
        ? "中国朝代尚未确定，不擅自添加具有明确朝代归属的冠帽、剪裁和配饰。"
        : null;
  const prompt = [
    `【群演形象｜${item.name}】`,
    "生成一张单独的16:9横版群演形象图，不使用资产卡、四宫格、多视图、表格、标签或文字。",
    `【画风】${GROUP_STYLE[settings.visualStandard]}。`,
    `【人数】画面中严格为${profile.count}。`,
    `【性别分配】${profile.gender}。`,
    `【身份与外貌】${profile.identity}。每个人必须是独立选角：五官、骨相、年龄感、发际线、发型、身高与体型明显不同；禁止复制脸、双胞胎感和同一模型批量换装。`,
    `【服饰】${profile.wardrobe}。服装必须各异但属于同一世界观，禁止整齐复制同一套衣服。`,
    eraRule ? `【时代硬锁】${eraRule}` : null,
    item.description.trim() ? `【剧本身份补充】${item.description.trim()}` : null,
    item.visualAnchor.trim() ? `【视觉补充】${item.visualAnchor.trim()}` : null,
    item.continuityNotes.trim() ? `【连续性补充】${item.continuityNotes.trim()}` : null,
    "【构图硬锁】所有人从头到脚完整入镜，双脚清晰可见，站姿自然，横向错落排布并留有可分割间距；人物之间不得大面积遮挡，不得裁头、裁脚，不得把任何人放进单独格子。纯净中性影棚背景，统一光向、曝光、镜头高度与画风。",
    "【禁止】禁止单人、人数不足或超出范围、同脸克隆、复制粘贴、相同服装、拥挤遮挡、半身像、裁切脚部、角色资产卡、四宫格、九宫格、多视图、场景叙事、战斗动作、文字、姓名、编号、Logo和水印。",
  ].filter((section): section is string => Boolean(section)).join("\n\n");
  return {
    prompt,
    warnings: compatibleWithChineseCostume && settings.costumeEra === "auto"
      ? ["尚未指定中国朝代，正式生成前需要人工确认年代。"]
      : [],
    standardLabel,
    eraLabel: compatibleWithChineseCostume ? era.label : null,
  };
}

function sourceLine(label: string, value: string) {
  return `${label}：${value.trim() || "待补充"}`;
}

function isLikelyFemale(item: AssetItem) {
  const identity = item.description.split("；")[0] ?? "";
  return /女|公主|夫人|小姐|王妃|皇后|妃|妻|妾|母|婆子|丫鬟|宫婢/.test(
    `${item.name} ${identity} ${item.visualAnchor}`,
  );
}

function primaryCharacterAppearance(item: AssetItem, settings: AssetStandardSettings) {
  if (item.kind !== "character") return null;
  const weights: Array<[string, number]> = [
    ["宫装", 10], ["褙子", 9], ["锦袍", 8], ["劲装", 8], ["黑袍", 8],
    ["官服", 7], ["长袍", 6], ["长裙", 6], ["白衣", 5], ["衣", 2],
    ["发髻", 3], ["束发", 3], ["冠", 3], ["腰带", 2], ["佩", 1],
  ];
  const candidates = item.visualAnchor.split(/[；;]/).map((value) => value.trim()).filter(Boolean);
  const selected = candidates
    .map((value) => ({
      value,
      score: weights.reduce((total, [keyword, weight]) => total + (value.includes(keyword) ? weight : 0), 0)
        - (/手腕|侧脸|掌印|眼眸|被掌掴/.test(value) ? 8 : 0),
    }))
    .sort((left, right) => right.score - left.score || right.value.length - left.value.length)[0]?.value ?? null;
  if (selected && settings.costumeEra === "ming" && isLikelyFemale(item) && selected.includes("宫装")) {
    return `${item.name}（明代皇室贵族日常正装：素白暗金织纹直领大襟短袄，配同色马面裙，盘髻配克制金簪与垂珠耳饰，气度尊贵清冷；非婚礼礼服，不用凤冠霞帔）`;
  }
  if (selected && settings.costumeEra === "ming" && !isLikelyFemale(item)) {
    return selected.replace("束发金冠", "束发先罩黑色网巾，外配简洁黑色明代巾冠；绝对不得金属冠、金冠或玄幻发冠");
  }
  return selected;
}

function finalComplianceLock(item: AssetItem) {
  if (item.kind === "character") {
    return "【生成前最终硬锁｜不得违反】必须严格生成单张9:16竖版2×2四宫格：左上仅正面头肩；右上仅标准90度侧面头肩；左下画面上边缘从锁骨以下开始，整个头、头发、脸、下巴和颈部上段必须完全在画外，绝对不得露脸；右下必须头脚完整、完全背面、绝不回头。四格必须同一人物、同一张脸、同一套服装、同一妆发，禁止四个不同人物。";
  }
  if (item.kind === "scene") {
    return "【生成前最终硬锁｜不得违反】必须是单张16:9同一场景五视图：正、反、左、右四个无人透视图，加一个黑白线稿顶视平面图；禁止任何人物、人体、服装和动作。";
  }
  return "【生成前最终硬锁｜不得违反】必须是单张9:16同一道具四宫格：上排两个不同局部特写，下排两个完整不同角度；禁止人物、人手、人体部位和四个不同道具。";
}

function specificDetails(item: AssetItem, settings: AssetStandardSettings) {
  const collectiveCharacter = item.kind === "character" && /们|众|护卫|侍女/.test(item.name);
  const primaryAppearance = primaryCharacterAppearance(item, settings);
  const selectionRule = item.kind === "scene"
    ? "内容取舍：下列剧情文本只用于判断场景功能、空间关系、陈设、材质与光线；忽略并禁止呈现其中的任何人物、人体、服装、动作和表演。无人场景规则优先级最高。"
    : item.kind === "prop"
      ? "内容取舍：下列剧情文本只用于判断道具功能、尺寸、结构、材质、工艺与磨损；忽略并禁止呈现持有者、人物、人手、人体、动作和场景表演。纯物品规则优先级最高。"
      : `内容取舍：只补充该角色本人的身份、外形、服装、材质与固定识别锚点，不把其他人物或场景混入资产卡。若资料出现多套服装，只选择身份辨识度最高的一套主造型，四格不得混搭寝衣、常服、礼服或不同剧情阶段。主造型锁定与历史服饰补充层的优先级高于下方原始视觉锚点，冲突细节必须忽略。${collectiveCharacter ? "该名称代表群体职能，本卡只展示一名标准代表个体，禁止多人群像。" : ""}`;
  return [
    "【本资产具体细节】",
    selectionRule,
    primaryAppearance ? `主造型锁定（四格唯一服装与妆发）：${primaryAppearance}` : null,
    sourceLine("剧本说明", item.description),
    sourceLine("视觉锚点", item.visualAnchor),
    sourceLine("连续性约束", item.continuityNotes),
  ].filter((line): line is string => Boolean(line)).join("\n");
}

function costumeLayer(item: AssetItem, settings: AssetStandardSettings) {
  const standard = VISUAL_STANDARD_OPTIONS.find((option) => option.id === settings.visualStandard);
  if (!standard?.compatibleWithChineseCostume) {
    return { rule: null, warning: null, eraLabel: null };
  }
  const era = COSTUME_ERA_OPTIONS.find((option) => option.id === settings.costumeEra)
    ?? COSTUME_ERA_OPTIONS[0];
  if (settings.costumeEra === "auto") {
    return {
      rule: item.kind === "character"
        ? "中国朝代尚未确定，不添加具体形制、品色、冠帽或配饰；正式生成前必须确认年代。"
        : "中国朝代尚未确定，不擅自补充跨年代建筑、工艺或器物。",
      warning: "尚未指定中国朝代，正式生成前需要人工确认年代。",
      eraLabel: era.label,
    };
  }
  if (item.kind !== "character") {
    const contextRule = settings.costumeEra === "ming"
      ? item.kind === "scene"
        ? "建筑、家具、照明和生活陈设锁定明代语境，结构与工艺服从场景身份和功能；禁止清代装饰体系、西式家具、现代灯具与现代材料。"
        : "器物的结构、纹样、材料和工艺锁定明代语境，按用途选择木、漆、铁、铜、瓷、玉、织物等合理材质；禁止清代制式、西式工业件与现代零件。"
      : "不得擅自混入其他朝代的标志性结构、工艺或器物。";
    return {
      rule: `时代语境锁定为${era.label}代；服饰训练资料只用于人物服饰，不能套到无人场景或纯道具。${contextRule}`,
      warning: null,
      eraLabel: era.label,
    };
  }
  const likelyFemale = isLikelyFemale(item);
  const rule = DETAILED_ERA_RULES[settings.costumeEra];
  if (rule && !likelyFemale) return { rule, warning: null, eraLabel: era.label };
  if (settings.costumeEra === "ming" && likelyFemale) {
    return { rule: MING_FEMALE_RULE, warning: null, eraLabel: era.label };
  }
  if (rule) {
    return {
      rule: `时代锁定为${era.label}代。现有训练资料是男性角色规范，不能套到该女性角色；女性服饰形制、发髻、品色与配饰必须另行补充考据。`,
      warning: `${era.label}代训练资料目前只覆盖男性角色，该女性角色不能自动套用。`,
      eraLabel: era.label,
    };
  }
  return {
    rule: `时代锁定为${era.label}代，但现有训练资料没有该朝代的详细服饰字典；不自动杜撰具体形制、品色、冠帽、面料或配饰。`,
    warning: `${era.label}代目前没有可直接套用的详细服饰规范。`,
    eraLabel: era.label,
  };
}

export function compileAssetPrompt(item: AssetItem, settings: AssetStandardSettings): CompiledAssetPrompt {
  const standard = VISUAL_STANDARD_OPTIONS.find((option) => option.id === settings.visualStandard)
    ?? VISUAL_STANDARD_OPTIONS[0];
  if (isCollectiveCharacter(item.kind, item.name)) {
    return compileCollectivePrompt(item, settings, standard.label);
  }
  const costume = costumeLayer(item, settings);
  const template = TEMPLATE_BY_STANDARD[settings.visualStandard][item.kind]
    .replaceAll("【场景名称】", `【${item.name}】`);
  const kindLabel = item.kind === "character" ? "角色" : item.kind === "scene" ? "场景" : "道具";
  const prompt = [
    `【${kindLabel}资产卡｜${item.name}】`,
    `【固定模板】\n${template}`,
    costume.rule ? `【历史与服饰补充层】\n${costume.rule}` : null,
    specificDetails(item, settings),
    finalComplianceLock(item),
  ].filter((section): section is string => Boolean(section)).join("\n\n");
  const warnings = costume.warning ? [costume.warning] : [];
  if (item.kind === "character" && !primaryCharacterAppearance(item, settings)) {
    warnings.push("该人物缺少可锁定的主造型视觉锚点，补全前不应进入生图队列。");
  }
  return {
    prompt,
    warnings,
    standardLabel: standard.label,
    eraLabel: costume.eraLabel,
  };
}
