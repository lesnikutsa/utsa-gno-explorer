export class CosmosRequestScope {
  constructor() {
    this.generation = 0
    this.current = null
  }

  begin(url, controller) {
    if (this.current) return null
    const request = { url, controller, generation: this.generation }
    this.current = request
    return request
  }

  isCurrent(request, url) {
    return this.current === request && request.generation === this.generation && request.url === url
  }

  finish(request) {
    if (this.current === request) this.current = null
  }

  reset() {
    this.generation += 1
    this.current?.controller.abort()
    this.current = null
  }
}
