package tencent

import (
	"context"
	"fmt"
	"time"

	"surveycontroller/surveycore/internal/model"
)

func (r Runner) Run(ctx context.Context, cfg *model.RuntimeConfig, handler EventHandler) (Result, error) {
	_ = r
	target := 1
	if cfg != nil && cfg.Target > 0 {
		target = cfg.Target
	}
	if handler != nil {
		handler(Event{
			Worker:  "Worker-1",
			Message: "腾讯问卷真实提交尚未接入",
			Fail:    true,
			Current: 0,
			Total:   target,
			Time:    time.Now(),
		})
	}
	if err := ctx.Err(); err != nil {
		return Result{Target: target, Status: "stopped"}, err
	}
	return Result{Target: target, Status: "unsupported"}, fmt.Errorf("腾讯问卷真实提交尚未接入，需要基于接口样本补齐提交参数和 live test")
}
