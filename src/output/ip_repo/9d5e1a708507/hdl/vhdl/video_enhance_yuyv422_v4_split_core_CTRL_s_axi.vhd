-- ==============================================================
-- Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2026.1 (64-bit)
-- Tool Version Limit: 2026.06
-- Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
-- Copyright 2022-2026 Advanced Micro Devices, Inc. All Rights Reserved.
-- 
-- ==============================================================
library IEEE;
use IEEE.STD_LOGIC_1164.all;
use IEEE.NUMERIC_STD.all;

entity video_enhance_yuyv422_v4_split_core_CTRL_s_axi is
generic (
    C_S_AXI_ADDR_WIDTH    : INTEGER := 8;
    C_S_AXI_DATA_WIDTH    : INTEGER := 32);
port (
    ACLK                  :in   STD_LOGIC;
    ARESET                :in   STD_LOGIC;
    ACLK_EN               :in   STD_LOGIC;
    AWADDR                :in   STD_LOGIC_VECTOR(C_S_AXI_ADDR_WIDTH-1 downto 0);
    AWVALID               :in   STD_LOGIC;
    AWREADY               :out  STD_LOGIC;
    WDATA                 :in   STD_LOGIC_VECTOR(C_S_AXI_DATA_WIDTH-1 downto 0);
    WSTRB                 :in   STD_LOGIC_VECTOR(C_S_AXI_DATA_WIDTH/8-1 downto 0);
    WVALID                :in   STD_LOGIC;
    WREADY                :out  STD_LOGIC;
    BRESP                 :out  STD_LOGIC_VECTOR(1 downto 0);
    BVALID                :out  STD_LOGIC;
    BREADY                :in   STD_LOGIC;
    ARADDR                :in   STD_LOGIC_VECTOR(C_S_AXI_ADDR_WIDTH-1 downto 0);
    ARVALID               :in   STD_LOGIC;
    ARREADY               :out  STD_LOGIC;
    RDATA                 :out  STD_LOGIC_VECTOR(C_S_AXI_DATA_WIDTH-1 downto 0);
    RRESP                 :out  STD_LOGIC_VECTOR(1 downto 0);
    RVALID                :out  STD_LOGIC;
    RREADY                :in   STD_LOGIC;
    interrupt             :out  STD_LOGIC;
    width                 :out  STD_LOGIC_VECTOR(31 downto 0);
    height                :out  STD_LOGIC_VECTOR(31 downto 0);
    mode                  :out  STD_LOGIC_VECTOR(31 downto 0);
    brightness            :out  STD_LOGIC_VECTOR(31 downto 0);
    gain_q8_8             :out  STD_LOGIC_VECTOR(31 downto 0);
    threshold             :out  STD_LOGIC_VECTOR(31 downto 0);
    sharp_q8_8            :out  STD_LOGIC_VECTOR(31 downto 0);
    filter_enable         :out  STD_LOGIC_VECTOR(31 downto 0);
    knee_out              :out  STD_LOGIC_VECTOR(31 downto 0);
    soft_q8_8             :out  STD_LOGIC_VECTOR(31 downto 0);
    noise_floor           :out  STD_LOGIC_VECTOR(31 downto 0);
    detail_limit          :out  STD_LOGIC_VECTOR(31 downto 0);
    dark_thr              :out  STD_LOGIC_VECTOR(31 downto 0);
    light_thr             :out  STD_LOGIC_VECTOR(31 downto 0);
    roi_enable            :out  STD_LOGIC_VECTOR(31 downto 0);
    roi_x                 :out  STD_LOGIC_VECTOR(31 downto 0);
    roi_y                 :out  STD_LOGIC_VECTOR(31 downto 0);
    roi_width             :out  STD_LOGIC_VECTOR(31 downto 0);
    roi_height            :out  STD_LOGIC_VECTOR(31 downto 0);
    discard_startup_frame :out  STD_LOGIC_VECTOR(31 downto 0);
    noise_floor_uv        :out  STD_LOGIC_VECTOR(31 downto 0);
    overshoot             :out  STD_LOGIC_VECTOR(31 downto 0);
    frame_count           :in   STD_LOGIC_VECTOR(31 downto 0);
    frame_count_ap_vld    :in   STD_LOGIC;
    stream_errors         :in   STD_LOGIC_VECTOR(31 downto 0);
    stream_errors_ap_vld  :in   STD_LOGIC;
    ap_start              :out  STD_LOGIC;
    ap_done               :in   STD_LOGIC;
    ap_ready              :in   STD_LOGIC;
    ap_idle               :in   STD_LOGIC
);
end entity video_enhance_yuyv422_v4_split_core_CTRL_s_axi;

-- ------------------------Address Info-------------------
-- Protocol Used: ap_ctrl_hs
--
-- 0x00 : Control signals
--        bit 0  - ap_start (Read/Write/COH)
--        bit 1  - ap_done (Read/COR)
--        bit 2  - ap_idle (Read)
--        bit 3  - ap_ready (Read/COR)
--        bit 7  - auto_restart (Read/Write)
--        bit 9  - interrupt (Read)
--        others - reserved
-- 0x04 : Global Interrupt Enable Register
--        bit 0  - Global Interrupt Enable (Read/Write)
--        others - reserved
-- 0x08 : IP Interrupt Enable Register (Read/Write)
--        bit 0 - enable ap_done interrupt (Read/Write)
--        bit 1 - enable ap_ready interrupt (Read/Write)
--        others - reserved
-- 0x0c : IP Interrupt Status Register (Read/TOW)
--        bit 0 - ap_done (Read/TOW)
--        bit 1 - ap_ready (Read/TOW)
--        others - reserved
-- 0x10 : Data signal of width
--        bit 31~0 - width[31:0] (Read/Write)
-- 0x14 : reserved
-- 0x18 : Data signal of height
--        bit 31~0 - height[31:0] (Read/Write)
-- 0x1c : reserved
-- 0x20 : Data signal of mode
--        bit 31~0 - mode[31:0] (Read/Write)
-- 0x24 : reserved
-- 0x28 : Data signal of brightness
--        bit 31~0 - brightness[31:0] (Read/Write)
-- 0x2c : reserved
-- 0x30 : Data signal of gain_q8_8
--        bit 31~0 - gain_q8_8[31:0] (Read/Write)
-- 0x34 : reserved
-- 0x38 : Data signal of threshold
--        bit 31~0 - threshold[31:0] (Read/Write)
-- 0x3c : reserved
-- 0x40 : Data signal of sharp_q8_8
--        bit 31~0 - sharp_q8_8[31:0] (Read/Write)
-- 0x44 : reserved
-- 0x48 : Data signal of filter_enable
--        bit 31~0 - filter_enable[31:0] (Read/Write)
-- 0x4c : reserved
-- 0x50 : Data signal of knee_out
--        bit 31~0 - knee_out[31:0] (Read/Write)
-- 0x54 : reserved
-- 0x58 : Data signal of soft_q8_8
--        bit 31~0 - soft_q8_8[31:0] (Read/Write)
-- 0x5c : reserved
-- 0x60 : Data signal of noise_floor
--        bit 31~0 - noise_floor[31:0] (Read/Write)
-- 0x64 : reserved
-- 0x68 : Data signal of detail_limit
--        bit 31~0 - detail_limit[31:0] (Read/Write)
-- 0x6c : reserved
-- 0x70 : Data signal of dark_thr
--        bit 31~0 - dark_thr[31:0] (Read/Write)
-- 0x74 : reserved
-- 0x78 : Data signal of light_thr
--        bit 31~0 - light_thr[31:0] (Read/Write)
-- 0x7c : reserved
-- 0x80 : Data signal of roi_enable
--        bit 31~0 - roi_enable[31:0] (Read/Write)
-- 0x84 : reserved
-- 0x88 : Data signal of roi_x
--        bit 31~0 - roi_x[31:0] (Read/Write)
-- 0x8c : reserved
-- 0x90 : Data signal of roi_y
--        bit 31~0 - roi_y[31:0] (Read/Write)
-- 0x94 : reserved
-- 0x98 : Data signal of roi_width
--        bit 31~0 - roi_width[31:0] (Read/Write)
-- 0x9c : reserved
-- 0xa0 : Data signal of roi_height
--        bit 31~0 - roi_height[31:0] (Read/Write)
-- 0xa4 : reserved
-- 0xa8 : Data signal of discard_startup_frame
--        bit 31~0 - discard_startup_frame[31:0] (Read/Write)
-- 0xac : reserved
-- 0xb0 : Data signal of noise_floor_uv
--        bit 31~0 - noise_floor_uv[31:0] (Read/Write)
-- 0xb4 : reserved
-- 0xb8 : Data signal of overshoot
--        bit 31~0 - overshoot[31:0] (Read/Write)
-- 0xbc : reserved
-- 0xc0 : Data signal of frame_count
--        bit 31~0 - frame_count[31:0] (Read)
-- 0xc4 : Control signal of frame_count
--        bit 0  - frame_count_ap_vld (Read/COR)
--        others - reserved
-- 0xd0 : Data signal of stream_errors
--        bit 31~0 - stream_errors[31:0] (Read)
-- 0xd4 : Control signal of stream_errors
--        bit 0  - stream_errors_ap_vld (Read/COR)
--        others - reserved
-- (SC = Self Clear, COR = Clear on Read, TOW = Toggle on Write, COH = Clear on Handshake)

architecture behave of video_enhance_yuyv422_v4_split_core_CTRL_s_axi is
attribute DowngradeIPIdentifiedWarnings : STRING;
attribute DowngradeIPIdentifiedWarnings of behave : architecture is "yes";
    type states is (wridle, wrdata, wrresp, wrreset, rdidle, rddata, rdreset);  -- read and write fsm states
    signal wstate  : states := wrreset;
    signal rstate  : states := rdreset;
    signal wnext, rnext: states;
    constant ADDR_AP_CTRL                      : INTEGER := 16#00#;
    constant ADDR_GIE                          : INTEGER := 16#04#;
    constant ADDR_IER                          : INTEGER := 16#08#;
    constant ADDR_ISR                          : INTEGER := 16#0c#;
    constant ADDR_WIDTH_DATA_0                 : INTEGER := 16#10#;
    constant ADDR_WIDTH_CTRL                   : INTEGER := 16#14#;
    constant ADDR_HEIGHT_DATA_0                : INTEGER := 16#18#;
    constant ADDR_HEIGHT_CTRL                  : INTEGER := 16#1c#;
    constant ADDR_MODE_DATA_0                  : INTEGER := 16#20#;
    constant ADDR_MODE_CTRL                    : INTEGER := 16#24#;
    constant ADDR_BRIGHTNESS_DATA_0            : INTEGER := 16#28#;
    constant ADDR_BRIGHTNESS_CTRL              : INTEGER := 16#2c#;
    constant ADDR_GAIN_Q8_8_DATA_0             : INTEGER := 16#30#;
    constant ADDR_GAIN_Q8_8_CTRL               : INTEGER := 16#34#;
    constant ADDR_THRESHOLD_DATA_0             : INTEGER := 16#38#;
    constant ADDR_THRESHOLD_CTRL               : INTEGER := 16#3c#;
    constant ADDR_SHARP_Q8_8_DATA_0            : INTEGER := 16#40#;
    constant ADDR_SHARP_Q8_8_CTRL              : INTEGER := 16#44#;
    constant ADDR_FILTER_ENABLE_DATA_0         : INTEGER := 16#48#;
    constant ADDR_FILTER_ENABLE_CTRL           : INTEGER := 16#4c#;
    constant ADDR_KNEE_OUT_DATA_0              : INTEGER := 16#50#;
    constant ADDR_KNEE_OUT_CTRL                : INTEGER := 16#54#;
    constant ADDR_SOFT_Q8_8_DATA_0             : INTEGER := 16#58#;
    constant ADDR_SOFT_Q8_8_CTRL               : INTEGER := 16#5c#;
    constant ADDR_NOISE_FLOOR_DATA_0           : INTEGER := 16#60#;
    constant ADDR_NOISE_FLOOR_CTRL             : INTEGER := 16#64#;
    constant ADDR_DETAIL_LIMIT_DATA_0          : INTEGER := 16#68#;
    constant ADDR_DETAIL_LIMIT_CTRL            : INTEGER := 16#6c#;
    constant ADDR_DARK_THR_DATA_0              : INTEGER := 16#70#;
    constant ADDR_DARK_THR_CTRL                : INTEGER := 16#74#;
    constant ADDR_LIGHT_THR_DATA_0             : INTEGER := 16#78#;
    constant ADDR_LIGHT_THR_CTRL               : INTEGER := 16#7c#;
    constant ADDR_ROI_ENABLE_DATA_0            : INTEGER := 16#80#;
    constant ADDR_ROI_ENABLE_CTRL              : INTEGER := 16#84#;
    constant ADDR_ROI_X_DATA_0                 : INTEGER := 16#88#;
    constant ADDR_ROI_X_CTRL                   : INTEGER := 16#8c#;
    constant ADDR_ROI_Y_DATA_0                 : INTEGER := 16#90#;
    constant ADDR_ROI_Y_CTRL                   : INTEGER := 16#94#;
    constant ADDR_ROI_WIDTH_DATA_0             : INTEGER := 16#98#;
    constant ADDR_ROI_WIDTH_CTRL               : INTEGER := 16#9c#;
    constant ADDR_ROI_HEIGHT_DATA_0            : INTEGER := 16#a0#;
    constant ADDR_ROI_HEIGHT_CTRL              : INTEGER := 16#a4#;
    constant ADDR_DISCARD_STARTUP_FRAME_DATA_0 : INTEGER := 16#a8#;
    constant ADDR_DISCARD_STARTUP_FRAME_CTRL   : INTEGER := 16#ac#;
    constant ADDR_NOISE_FLOOR_UV_DATA_0        : INTEGER := 16#b0#;
    constant ADDR_NOISE_FLOOR_UV_CTRL          : INTEGER := 16#b4#;
    constant ADDR_OVERSHOOT_DATA_0             : INTEGER := 16#b8#;
    constant ADDR_OVERSHOOT_CTRL               : INTEGER := 16#bc#;
    constant ADDR_FRAME_COUNT_DATA_0           : INTEGER := 16#c0#;
    constant ADDR_FRAME_COUNT_CTRL             : INTEGER := 16#c4#;
    constant ADDR_STREAM_ERRORS_DATA_0         : INTEGER := 16#d0#;
    constant ADDR_STREAM_ERRORS_CTRL           : INTEGER := 16#d4#;
    constant ADDR_BITS         : INTEGER := 8;

    signal AWREADY_t           : STD_LOGIC;
    signal WREADY_t            : STD_LOGIC;
    signal ARREADY_t           : STD_LOGIC;
    signal RVALID_t            : STD_LOGIC;
    signal BVALID_t            : STD_LOGIC;
    signal waddr               : UNSIGNED(ADDR_BITS-1 downto 0);
    signal wmask               : UNSIGNED(C_S_AXI_DATA_WIDTH-1 downto 0);
    signal aw_hs               : STD_LOGIC;
    signal w_hs                : STD_LOGIC;
    signal rdata_data          : UNSIGNED(C_S_AXI_DATA_WIDTH-1 downto 0);
    signal ar_hs               : STD_LOGIC;
    signal raddr               : UNSIGNED(ADDR_BITS-1 downto 0);
    -- internal registers
    signal int_ap_idle         : STD_LOGIC := '0';
    signal int_ap_ready        : STD_LOGIC := '0';
    signal task_ap_ready       : STD_LOGIC;
    signal int_ap_done         : STD_LOGIC := '0';
    signal task_ap_done        : STD_LOGIC;
    signal int_task_ap_done    : STD_LOGIC := '0';
    signal int_ap_start        : STD_LOGIC := '0';
    signal int_interrupt       : STD_LOGIC := '0';
    signal int_auto_restart    : STD_LOGIC := '0';
    signal auto_restart_status : STD_LOGIC := '0';
    signal auto_restart_done   : STD_LOGIC;
    signal int_gie             : STD_LOGIC := '0';
    signal int_ier             : UNSIGNED(1 downto 0) := (others => '0');
    signal int_isr             : UNSIGNED(1 downto 0) := (others => '0');
    signal int_width           : UNSIGNED(31 downto 0) := (others => '0');
    signal int_height          : UNSIGNED(31 downto 0) := (others => '0');
    signal int_mode            : UNSIGNED(31 downto 0) := (others => '0');
    signal int_brightness      : UNSIGNED(31 downto 0) := (others => '0');
    signal int_gain_q8_8       : UNSIGNED(31 downto 0) := (others => '0');
    signal int_threshold       : UNSIGNED(31 downto 0) := (others => '0');
    signal int_sharp_q8_8      : UNSIGNED(31 downto 0) := (others => '0');
    signal int_filter_enable   : UNSIGNED(31 downto 0) := (others => '0');
    signal int_knee_out        : UNSIGNED(31 downto 0) := (others => '0');
    signal int_soft_q8_8       : UNSIGNED(31 downto 0) := (others => '0');
    signal int_noise_floor     : UNSIGNED(31 downto 0) := (others => '0');
    signal int_detail_limit    : UNSIGNED(31 downto 0) := (others => '0');
    signal int_dark_thr        : UNSIGNED(31 downto 0) := (others => '0');
    signal int_light_thr       : UNSIGNED(31 downto 0) := (others => '0');
    signal int_roi_enable      : UNSIGNED(31 downto 0) := (others => '0');
    signal int_roi_x           : UNSIGNED(31 downto 0) := (others => '0');
    signal int_roi_y           : UNSIGNED(31 downto 0) := (others => '0');
    signal int_roi_width       : UNSIGNED(31 downto 0) := (others => '0');
    signal int_roi_height      : UNSIGNED(31 downto 0) := (others => '0');
    signal int_discard_startup_frame : UNSIGNED(31 downto 0) := (others => '0');
    signal int_noise_floor_uv  : UNSIGNED(31 downto 0) := (others => '0');
    signal int_overshoot       : UNSIGNED(31 downto 0) := (others => '0');
    signal int_frame_count_ap_vld : STD_LOGIC;
    signal int_frame_count     : UNSIGNED(31 downto 0) := (others => '0');
    signal int_stream_errors_ap_vld : STD_LOGIC;
    signal int_stream_errors   : UNSIGNED(31 downto 0) := (others => '0');


begin
-- ----------------------- Instantiation------------------


-- ----------------------- AXI WRITE ---------------------
    AWREADY_t <=  '1' when wstate = wridle else '0';
    AWREADY   <=  AWREADY_t;
    WREADY_t  <=  '1' when wstate = wrdata else '0';
    WREADY    <=  WREADY_t;
    BVALID_t  <=  '1' when wstate = wrresp else '0';
    BVALID    <=  BVALID_t;
    BRESP     <=  "00";  -- OKAY
    wmask     <=  (31 downto 24 => WSTRB(3), 23 downto 16 => WSTRB(2), 15 downto 8 => WSTRB(1), 7 downto 0 => WSTRB(0));
    aw_hs     <=  AWVALID and AWREADY_t;
    w_hs      <=  WVALID and WREADY_t;

    -- write FSM
    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                wstate <= wrreset;
            elsif (ACLK_EN = '1') then
                wstate <= wnext;
            end if;
        end if;
    end process;

    process (wstate, AWVALID, WVALID, BREADY, BVALID_t)
    begin
        case (wstate) is
        when wridle =>
            if (AWVALID = '1') then
                wnext <= wrdata;
            else
                wnext <= wridle;
            end if;
        when wrdata =>
            if (WVALID = '1') then
                wnext <= wrresp;
            else
                wnext <= wrdata;
            end if;
        when wrresp =>
            if (BREADY = '1' and BVALID_t = '1') then
                wnext <= wridle;
            else
                wnext <= wrresp;
            end if;
        when others =>
            wnext <= wridle;
        end case;
    end process;

    waddr_proc : process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ACLK_EN = '1') then
                if (aw_hs = '1') then
                    waddr <= UNSIGNED(AWADDR(ADDR_BITS-1 downto 2) & (1 downto 0 => '0'));
                end if;
            end if;
        end if;
    end process;

-- ----------------------- AXI READ ----------------------
    ARREADY_t <= '1' when (rstate = rdidle) else '0';
    ARREADY <= ARREADY_t;
    RDATA   <= STD_LOGIC_VECTOR(rdata_data);
    RRESP   <= "00";  -- OKAY
    RVALID_t  <= '1' when (rstate = rddata) else '0';
    RVALID    <= RVALID_t;
    ar_hs   <= ARVALID and ARREADY_t;
    raddr   <= UNSIGNED(ARADDR(ADDR_BITS-1 downto 0));

    -- read FSM
    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                rstate <= rdreset;
            elsif (ACLK_EN = '1') then
                rstate <= rnext;
            end if;
        end if;
    end process;

    process (rstate, ARVALID, RREADY, RVALID_t)
    begin
        case (rstate) is
        when rdidle =>
            if (ARVALID = '1') then
                rnext <= rddata;
            else
                rnext <= rdidle;
            end if;
        when rddata =>
            if (RREADY = '1' and RVALID_t = '1') then
                rnext <= rdidle;
            else
                rnext <= rddata;
            end if;
        when others =>
            rnext <= rdidle;
        end case;
    end process;

    rdata_proc : process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ACLK_EN = '1') then
                if (ar_hs = '1') then
                    rdata_data <= (others => '0');
                    case (TO_INTEGER(raddr)) is
                    when ADDR_AP_CTRL =>
                        rdata_data(9) <= int_interrupt;
                        rdata_data(7) <= int_auto_restart;
                        rdata_data(3) <= int_ap_ready;
                        rdata_data(2) <= int_ap_idle;
                        rdata_data(1) <= int_task_ap_done;
                        rdata_data(0) <= int_ap_start;
                    when ADDR_GIE =>
                        rdata_data(0) <= int_gie;
                    when ADDR_IER =>
                        rdata_data(1 downto 0) <= int_ier;
                    when ADDR_ISR =>
                        rdata_data(1 downto 0) <= int_isr;
                    when ADDR_WIDTH_DATA_0 =>
                        rdata_data <= RESIZE(int_width(31 downto 0), 32);
                    when ADDR_HEIGHT_DATA_0 =>
                        rdata_data <= RESIZE(int_height(31 downto 0), 32);
                    when ADDR_MODE_DATA_0 =>
                        rdata_data <= RESIZE(int_mode(31 downto 0), 32);
                    when ADDR_BRIGHTNESS_DATA_0 =>
                        rdata_data <= RESIZE(int_brightness(31 downto 0), 32);
                    when ADDR_GAIN_Q8_8_DATA_0 =>
                        rdata_data <= RESIZE(int_gain_q8_8(31 downto 0), 32);
                    when ADDR_THRESHOLD_DATA_0 =>
                        rdata_data <= RESIZE(int_threshold(31 downto 0), 32);
                    when ADDR_SHARP_Q8_8_DATA_0 =>
                        rdata_data <= RESIZE(int_sharp_q8_8(31 downto 0), 32);
                    when ADDR_FILTER_ENABLE_DATA_0 =>
                        rdata_data <= RESIZE(int_filter_enable(31 downto 0), 32);
                    when ADDR_KNEE_OUT_DATA_0 =>
                        rdata_data <= RESIZE(int_knee_out(31 downto 0), 32);
                    when ADDR_SOFT_Q8_8_DATA_0 =>
                        rdata_data <= RESIZE(int_soft_q8_8(31 downto 0), 32);
                    when ADDR_NOISE_FLOOR_DATA_0 =>
                        rdata_data <= RESIZE(int_noise_floor(31 downto 0), 32);
                    when ADDR_DETAIL_LIMIT_DATA_0 =>
                        rdata_data <= RESIZE(int_detail_limit(31 downto 0), 32);
                    when ADDR_DARK_THR_DATA_0 =>
                        rdata_data <= RESIZE(int_dark_thr(31 downto 0), 32);
                    when ADDR_LIGHT_THR_DATA_0 =>
                        rdata_data <= RESIZE(int_light_thr(31 downto 0), 32);
                    when ADDR_ROI_ENABLE_DATA_0 =>
                        rdata_data <= RESIZE(int_roi_enable(31 downto 0), 32);
                    when ADDR_ROI_X_DATA_0 =>
                        rdata_data <= RESIZE(int_roi_x(31 downto 0), 32);
                    when ADDR_ROI_Y_DATA_0 =>
                        rdata_data <= RESIZE(int_roi_y(31 downto 0), 32);
                    when ADDR_ROI_WIDTH_DATA_0 =>
                        rdata_data <= RESIZE(int_roi_width(31 downto 0), 32);
                    when ADDR_ROI_HEIGHT_DATA_0 =>
                        rdata_data <= RESIZE(int_roi_height(31 downto 0), 32);
                    when ADDR_DISCARD_STARTUP_FRAME_DATA_0 =>
                        rdata_data <= RESIZE(int_discard_startup_frame(31 downto 0), 32);
                    when ADDR_NOISE_FLOOR_UV_DATA_0 =>
                        rdata_data <= RESIZE(int_noise_floor_uv(31 downto 0), 32);
                    when ADDR_OVERSHOOT_DATA_0 =>
                        rdata_data <= RESIZE(int_overshoot(31 downto 0), 32);
                    when ADDR_FRAME_COUNT_DATA_0 =>
                        rdata_data <= RESIZE(int_frame_count(31 downto 0), 32);
                    when ADDR_FRAME_COUNT_CTRL =>
                        rdata_data(0) <= int_frame_count_ap_vld;
                    when ADDR_STREAM_ERRORS_DATA_0 =>
                        rdata_data <= RESIZE(int_stream_errors(31 downto 0), 32);
                    when ADDR_STREAM_ERRORS_CTRL =>
                        rdata_data(0) <= int_stream_errors_ap_vld;
                    when others =>
                        NULL;
                    end case;
                end if;
            end if;
        end if;
    end process;

-- ----------------------- Register logic ----------------
    interrupt            <= int_interrupt;
    ap_start             <= int_ap_start;
    task_ap_done         <= (ap_done and not auto_restart_status) or auto_restart_done;
    task_ap_ready        <= ap_ready and not int_auto_restart;
    auto_restart_done    <= auto_restart_status and (ap_idle and not int_ap_idle);
    width                <= STD_LOGIC_VECTOR(int_width);
    height               <= STD_LOGIC_VECTOR(int_height);
    mode                 <= STD_LOGIC_VECTOR(int_mode);
    brightness           <= STD_LOGIC_VECTOR(int_brightness);
    gain_q8_8            <= STD_LOGIC_VECTOR(int_gain_q8_8);
    threshold            <= STD_LOGIC_VECTOR(int_threshold);
    sharp_q8_8           <= STD_LOGIC_VECTOR(int_sharp_q8_8);
    filter_enable        <= STD_LOGIC_VECTOR(int_filter_enable);
    knee_out             <= STD_LOGIC_VECTOR(int_knee_out);
    soft_q8_8            <= STD_LOGIC_VECTOR(int_soft_q8_8);
    noise_floor          <= STD_LOGIC_VECTOR(int_noise_floor);
    detail_limit         <= STD_LOGIC_VECTOR(int_detail_limit);
    dark_thr             <= STD_LOGIC_VECTOR(int_dark_thr);
    light_thr            <= STD_LOGIC_VECTOR(int_light_thr);
    roi_enable           <= STD_LOGIC_VECTOR(int_roi_enable);
    roi_x                <= STD_LOGIC_VECTOR(int_roi_x);
    roi_y                <= STD_LOGIC_VECTOR(int_roi_y);
    roi_width            <= STD_LOGIC_VECTOR(int_roi_width);
    roi_height           <= STD_LOGIC_VECTOR(int_roi_height);
    discard_startup_frame <= STD_LOGIC_VECTOR(int_discard_startup_frame);
    noise_floor_uv       <= STD_LOGIC_VECTOR(int_noise_floor_uv);
    overshoot            <= STD_LOGIC_VECTOR(int_overshoot);

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_interrupt <= '0';
            elsif (ACLK_EN = '1') then
                if (int_gie = '1' and (int_isr(0) or int_isr(1)) = '1') then
                    int_interrupt <= '1';
                else
                    int_interrupt <= '0';
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_ap_start <= '0';
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_AP_CTRL and WSTRB(0) = '1' and WDATA(0) = '1') then
                    int_ap_start <= '1';
                elsif (ap_ready = '1') then
                    int_ap_start <= int_auto_restart; -- clear on handshake/auto restart
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_ap_done <= '0';
            elsif (ACLK_EN = '1') then
                if (true) then
                    int_ap_done <= ap_done;
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_task_ap_done <= '0';
            elsif (ACLK_EN = '1') then
                if (task_ap_done = '1') then
                    int_task_ap_done <= '1';
                elsif (ar_hs = '1' and raddr = ADDR_AP_CTRL) then
                    int_task_ap_done <= '0'; -- clear on read
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_ap_idle <= '0';
            elsif (ACLK_EN = '1') then
                if (true) then
                    int_ap_idle <= ap_idle;
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_ap_ready <= '0';
            elsif (ACLK_EN = '1') then
                if (task_ap_ready = '1') then
                    int_ap_ready <= '1';
                elsif (ar_hs = '1' and raddr = ADDR_AP_CTRL) then
                    int_ap_ready <= '0';
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_auto_restart <= '0';
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_AP_CTRL and WSTRB(0) = '1') then
                    int_auto_restart <= WDATA(7);
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                auto_restart_status <= '0';
            elsif (ACLK_EN = '1') then
                if (int_auto_restart = '1') then
                    auto_restart_status <= '1';
                elsif (ap_idle = '1') then
                    auto_restart_status <= '0';
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_gie <= '0';
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_GIE and WSTRB(0) = '1') then
                    int_gie <= WDATA(0);
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_ier <= (others=>'0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_IER and WSTRB(0) = '1') then
                    int_ier <= UNSIGNED(WDATA(1 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_isr(0) <= '0';
            elsif (ACLK_EN = '1') then
                if (int_ier(0) = '1' and ap_done = '1') then
                    int_isr(0) <= '1';
                elsif (w_hs = '1' and waddr = ADDR_ISR and WSTRB(0) = '1') then
                    int_isr(0) <= int_isr(0) xor WDATA(0); -- toggle on write
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_isr(1) <= '0';
            elsif (ACLK_EN = '1') then
                if (int_ier(1) = '1' and ap_ready = '1') then
                    int_isr(1) <= '1';
                elsif (w_hs = '1' and waddr = ADDR_ISR and WSTRB(0) = '1') then
                    int_isr(1) <= int_isr(1) xor WDATA(1); -- toggle on write
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_width(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_WIDTH_DATA_0) then
                    int_width(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_width(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_height(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_HEIGHT_DATA_0) then
                    int_height(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_height(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_mode(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_MODE_DATA_0) then
                    int_mode(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_mode(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_brightness(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_BRIGHTNESS_DATA_0) then
                    int_brightness(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_brightness(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_gain_q8_8(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_GAIN_Q8_8_DATA_0) then
                    int_gain_q8_8(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_gain_q8_8(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_threshold(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_THRESHOLD_DATA_0) then
                    int_threshold(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_threshold(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_sharp_q8_8(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_SHARP_Q8_8_DATA_0) then
                    int_sharp_q8_8(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_sharp_q8_8(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_filter_enable(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_FILTER_ENABLE_DATA_0) then
                    int_filter_enable(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_filter_enable(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_knee_out(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_KNEE_OUT_DATA_0) then
                    int_knee_out(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_knee_out(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_soft_q8_8(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_SOFT_Q8_8_DATA_0) then
                    int_soft_q8_8(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_soft_q8_8(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_noise_floor(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_NOISE_FLOOR_DATA_0) then
                    int_noise_floor(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_noise_floor(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_detail_limit(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_DETAIL_LIMIT_DATA_0) then
                    int_detail_limit(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_detail_limit(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_dark_thr(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_DARK_THR_DATA_0) then
                    int_dark_thr(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_dark_thr(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_light_thr(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_LIGHT_THR_DATA_0) then
                    int_light_thr(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_light_thr(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_roi_enable(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_ROI_ENABLE_DATA_0) then
                    int_roi_enable(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_roi_enable(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_roi_x(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_ROI_X_DATA_0) then
                    int_roi_x(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_roi_x(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_roi_y(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_ROI_Y_DATA_0) then
                    int_roi_y(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_roi_y(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_roi_width(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_ROI_WIDTH_DATA_0) then
                    int_roi_width(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_roi_width(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_roi_height(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_ROI_HEIGHT_DATA_0) then
                    int_roi_height(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_roi_height(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_discard_startup_frame(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_DISCARD_STARTUP_FRAME_DATA_0) then
                    int_discard_startup_frame(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_discard_startup_frame(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_noise_floor_uv(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_NOISE_FLOOR_UV_DATA_0) then
                    int_noise_floor_uv(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_noise_floor_uv(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_overshoot(31 downto 0) <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (w_hs = '1' and waddr = ADDR_OVERSHOOT_DATA_0) then
                    int_overshoot(31 downto 0) <= (UNSIGNED(WDATA(31 downto 0)) and wmask(31 downto 0)) or ((not wmask(31 downto 0)) and int_overshoot(31 downto 0));
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_frame_count <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (frame_count_ap_vld = '1') then
                    int_frame_count <= UNSIGNED(frame_count);
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_frame_count_ap_vld <= '0';
            elsif (ACLK_EN = '1') then
                if (frame_count_ap_vld = '1') then
                    int_frame_count_ap_vld <= '1';
                elsif (ar_hs = '1' and raddr = ADDR_FRAME_COUNT_CTRL) then
                    int_frame_count_ap_vld <= '0'; -- clear on read
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_stream_errors <= (others => '0');
            elsif (ACLK_EN = '1') then
                if (stream_errors_ap_vld = '1') then
                    int_stream_errors <= UNSIGNED(stream_errors);
                end if;
            end if;
        end if;
    end process;

    process (ACLK)
    begin
        if (ACLK'event and ACLK = '1') then
            if (ARESET = '1') then
                int_stream_errors_ap_vld <= '0';
            elsif (ACLK_EN = '1') then
                if (stream_errors_ap_vld = '1') then
                    int_stream_errors_ap_vld <= '1';
                elsif (ar_hs = '1' and raddr = ADDR_STREAM_ERRORS_CTRL) then
                    int_stream_errors_ap_vld <= '0'; -- clear on read
                end if;
            end if;
        end if;
    end process;


-- ----------------------- Memory logic ------------------

end architecture behave;
